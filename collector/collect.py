#!/usr/bin/env python3
"""Observatory collector: reads report histories from git and writes the
dataset described in DATA.md.  Python 3.11+, standard library plus `git`."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

FORMAT = 1
KINDS = ("bench", "fuzz", "conformance")
MATRICES = ("wire", "codegen")
STATES = ("supported", "partial", "ignored", "unsupported")
UNRELEASED = "unreleased"
INT_RE = re.compile(r"^(0|[1-9][0-9]*)$")


class SourceError(Exception):
    """A source can't be published; the message becomes its `reason`."""


class ConfigError(Exception):
    """sources.toml is bad."""


def warn(msg):
    print(f"warning: {msg}", file=sys.stderr)


# ---------------------------------------------------------------- git access

class Tag:
    def __init__(self, name, version, commit, date):
        self.name, self.version, self.commit, self.date = name, version, commit, date


def utc(iso):
    """Any ISO 8601 timestamp as `YYYY-MM-DDTHH:MM:SSZ`."""
    d = datetime.fromisoformat(iso)
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Repo:
    """One repository, read through git only.  Only the read-only commands
    log, show, rev-list, merge-base, for-each-ref, cat-file, rev-parse are
    used on a `--local` checkout; clone/fetch run only in the cache."""

    def __init__(self, cfg, path, writable):
        self.name = cfg["name"]
        self.url = cfg["url"]
        self.default_branch = cfg["default_branch"]
        self.tag_re = cfg["tag_re"]
        self.path = Path(path)
        self.writable = writable  # True for our own cache clone
        self._ancestors = {}
        self._tags = None
        self._fetched = set()
        self._prepared = False

    def git(self, *args, check=True):
        env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
        p = subprocess.run(["git", "-C", str(self.path), *args],
                           capture_output=True, env=env)
        if check and p.returncode != 0:
            err = p.stderr.decode(errors="replace").strip().splitlines()
            raise SourceError(f"git {args[0]} failed in {self.name}: "
                              f"{err[-1] if err else p.returncode}")
        return p

    def prepare(self, branch):
        """Make `origin/<branch>` and the tags available (cache clones only)."""
        if not self.writable:
            return
        if not self._prepared:
            if not (self.path / ".git").exists() and not (self.path / "HEAD").exists():
                self.path.parent.mkdir(parents=True, exist_ok=True)
                p = subprocess.run(
                    ["git", "clone", "--filter=blob:none", "--no-checkout",
                     self.url, str(self.path)], capture_output=True)
                if p.returncode != 0:
                    shutil.rmtree(self.path, ignore_errors=True)
                    err = p.stderr.decode(errors="replace").strip().splitlines()
                    raise SourceError(f"cannot clone {self.url}: "
                                      f"{err[-1] if err else p.returncode}")
            self.git("fetch", "--quiet", "--tags", "--force", "origin")
            self._prepared = True
        if branch not in self._fetched:
            self.git("fetch", "--quiet", "origin",
                     f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
            self._fetched.add(branch)

    def ref(self, branch):
        self.prepare(branch)
        ref = f"refs/remotes/origin/{branch}"
        p = self.git("rev-parse", "--verify", "--quiet", ref + "^{commit}", check=False)
        if p.returncode != 0:
            raise SourceError(f"branch {branch} not found in {self.name}")
        return ref

    def tags(self):
        if self._tags is None:
            fmt = "%(refname:strip=2)%09%(objectname)%09%(*objectname)%09" \
                  "%(committerdate:iso-strict)%09%(*committerdate:iso-strict)"
            out = self.git("for-each-ref", f"--format={fmt}", "refs/tags").stdout.decode()
            tags = []
            for line in out.splitlines():
                name, obj, peeled, cdate, pdate = (line.split("\t") + [""] * 5)[:5]
                m = self.tag_re.search(name)
                if not m:
                    continue
                commit, date = (peeled, pdate) if peeled else (obj, cdate)
                if not date:
                    continue
                tags.append(Tag(name, m.group("version"), commit, utc(date)))
            tags.sort(key=lambda t: (t.date, t.name))
            self._tags = tags
        return self._tags

    def resolve_commit(self, rev):
        """Full hex of a commit that exists here, else None."""
        if not isinstance(rev, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", rev):
            return None
        p = self.git("rev-parse", "--verify", "--quiet", rev + "^{commit}", check=False)
        return p.stdout.decode().strip() if p.returncode == 0 else None

    def is_ancestor(self, commit, tag):
        key = (commit, tag.name)
        if key not in self._ancestors:
            p = self.git("merge-base", "--is-ancestor", commit, tag.commit, check=False)
            if p.returncode not in (0, 1):
                raise SourceError(f"git merge-base failed in {self.name}")
            self._ancestors[key] = p.returncode == 0
        return self._ancestors[key]

    def cycle_tag(self, commit):
        """The oldest tag whose history contains `commit`, or None."""
        for tag in self.tags():
            if self.is_ancestor(commit, tag):
                return tag
        return None

    def history(self, ref, path):
        """[(commit, date)] first-parent, oldest first, for commits touching path."""
        out = self.git("log", "--first-parent", "--reverse", "--format=%H%x09%cI",
                       ref, "--", path).stdout.decode()
        res = []
        for line in out.splitlines():
            h, d = line.split("\t")
            res.append((h, utc(d)))
        return res

    def show(self, rev, path):
        p = self.git("show", f"{rev}:{path}", check=False)
        return p.stdout if p.returncode == 0 else None


# ------------------------------------------------------------- normalisation

class Norm:
    """A version's report, normalised: `rows` maps (key, metric) to
    (value, unit, type); `shard` is the per-version file's content."""

    def __init__(self, rows, shard, commit=None, toolchain=None, run=None):
        self.rows, self.shard = rows, shard
        self.commit, self.toolchain, self.run = commit, toolchain, run


def _str_or_none(v):
    return v if isinstance(v, str) and v else None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def normalise_bench(rep):
    if not isinstance(rep, dict) or not isinstance(rep.get("benches"), dict):
        raise ValueError("no `benches` object")
    rows, benches = {}, {}
    for bid, entry in rep["benches"].items():
        if not isinstance(entry, dict):
            raise ValueError(f"bench {bid} is not an object")
        out = {}
        for name, v in entry.items():
            if isinstance(v, dict):  # format 2: {value, runner, spread?}
                runner = v.get("runner")
                metric = name if runner in (None, "") else f"{name}@{runner}"
                value = _num(v.get("value"))
                unit = name
            else:                    # format 1: {"ir": N}
                metric = "instructions" if name == "ir" else name
                value, unit = _num(v), metric
            out[metric] = value
            rows[(bid, metric)] = (value, unit, "number")
        benches[bid] = out
    return Norm(rows, {"benches": benches}, _str_or_none(rep.get("commit")),
                _str_or_none(rep.get("toolchain")), _str_or_none(rep.get("run")))


FUZZ_METRICS = (("executions", "executions"), ("corpus", "inputs"),
                ("findings", "findings"), ("seconds", "s"))


def normalise_fuzz(rep):
    if not isinstance(rep, dict):
        raise ValueError("not an object")
    rows = {}
    for target, t in (rep.get("targets") or {}).items():
        broken = not isinstance(t, dict) or "error" in t
        for metric, unit in FUZZ_METRICS:
            rows[(target, metric)] = (None if broken else _num(t.get(metric)), unit, "number")
    pt = rep.get("proptest")
    if isinstance(pt, dict):
        for prop, verdict in (pt.get("properties") or {}).items():
            v = verdict if verdict in ("pass", "fail") else None
            rows[(f"proptest/{prop}", "verdict")] = (v, None, "verdict")
        rows[("proptest", "cases")] = (_num(pt.get("cases")), "cases", "number")
    shard = {k: v for k, v in rep.items() if k not in ("commit", "toolchain", "date", "run")}
    return Norm(rows, shard, _str_or_none(rep.get("commit")),
                _str_or_none(rep.get("toolchain")), _str_or_none(rep.get("run")))


def _sorted_list(v):
    return sorted(v) if isinstance(v, list) else None


def normalise_conformance(rep):
    if not isinstance(rep, dict):
        raise ValueError("not an object")
    if isinstance(rep.get("generators"), list):
        subjects = [(g["name"], g.get("support") or {}) for g in rep["generators"]]
    elif isinstance(rep.get("support"), dict):
        subjects = [(rep.get("runtime") or "runtime", rep["support"])]
    else:
        raise ValueError("neither `generators` nor `support`")
    rows, shard = {}, {}
    for subject, support in subjects:
        sh = shard[subject] = {}
        for feat, s in support.items():
            state = s.get("state") if isinstance(s, dict) else None
            state = state if state in STATES else None
            rows[(f"{subject}/{feat}", "state")] = (state, None, "state")
            s = s if isinstance(s, dict) else {}
            sh[feat] = {"state": state, "proven_by": _sorted_list(s.get("proven_by")),
                        "note": s.get("note"), "tracking": s.get("tracking"),
                        "failing": _sorted_list(s.get("failing"))}
    return Norm(rows, {"subjects": shard})


NORMALISERS = {"bench": normalise_bench, "fuzz": normalise_fuzz,
               "conformance": normalise_conformance}


def feature_map(doc):
    """`{id: {title, description}}` from a features list or a features file."""
    items = doc.get("features") if isinstance(doc, dict) else None
    if not isinstance(items, list):
        raise ValueError("no `features` list")
    return {f["id"]: {"title": f.get("title"), "description": f.get("description")}
            for f in items}


# ------------------------------------------------------------------- writing

class Version:
    def __init__(self, id, commit, date, cycle, norm):
        self.id, self.commit, self.date, self.cycle = id, commit, date, cycle
        self.norm = norm
        self.label = self.release = None


def dumps(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def put(out, directory, stem, obj):
    """Write `obj` as `<directory>/<stem>.<hash>.json`; return the relative path."""
    data = dumps(obj)
    rel = f"{directory}/{stem}.{hashlib.sha256(data).hexdigest()[:12]}.json"
    path = Path(out) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel


def split_key(key):
    """(group, param) of a metric key."""
    if "/" not in key:
        return None, None
    group, last = key.rsplit("/", 1)
    return group, (int(last) if INT_RE.match(last) else None)


def publish_source(out, src, versions, tags, features):
    """Label `versions` (already in order, `.cycle` set), write the source's
    files under `<out>/sources/<id>/`, return the index's relative path.

    `src`: id, kind, title, repo, repo_url, branch, path, matrix.
    `tags`: {cycle id: Tag-like with .name and .date} for released cycles."""
    sid = src["id"]
    base = f"sources/{sid}"
    counts, last = {}, {}
    for i, v in enumerate(versions):
        counts[v.cycle] = counts.get(v.cycle, 0) + 1
        v.label = f"{v.cycle}-dev.{counts[v.cycle]}"
        v.release = None
        last[v.cycle] = i
    for cycle, i in last.items():
        if cycle != UNRELEASED:
            versions[i].release = cycle

    defs = {}
    for v in versions:
        for (key, metric), (_, unit, typ) in v.norm.rows.items():
            defs.setdefault((key, metric), (unit, typ))
    order = sorted(defs)
    metrics = []
    for key, metric in order:
        unit, typ = defs[(key, metric)]
        group, param = split_key(key)
        metrics.append({"key": key, "metric": metric, "unit": unit, "type": typ,
                        "group": group, "param": param})

    def chunk(name, idxs):
        values = [[versions[j].norm.rows.get(m, (None,))[0] for j in idxs] for m in order]
        return put(out, base, name, {"versions": idxs, "values": values})

    index_versions = []
    for i, v in enumerate(versions):
        shard = put(out, f"{base}/v", v.id, v.norm.shard)
        index_versions.append({
            "id": v.id, "commit": v.commit, "date": v.date, "cycle": v.cycle,
            "label": v.label, "release": v.release, "run": v.norm.run,
            "toolchain": v.norm.toolchain, "shard": shard})

    present = {v.cycle for v in versions}
    cycles = []
    released = sorted((c for c in present if c != UNRELEASED),
                      key=lambda c: (tags[c].date, c))
    for c in released:
        idxs = [i for i, v in enumerate(versions) if v.cycle == c]
        cycles.append({"id": c, "tag": tags[c].name, "date": tags[c].date,
                       "chunk": chunk(f"cycle-{c}", idxs)})
    if UNRELEASED in present:
        idxs = [i for i, v in enumerate(versions) if v.cycle == UNRELEASED]
        cycles.append({"id": UNRELEASED, "tag": None, "date": None,
                       "chunk": chunk(f"cycle-{UNRELEASED}", idxs)})
    releases = chunk("releases", [i for i, v in enumerate(versions) if v.release])

    index = {"id": sid, "kind": src["kind"], "title": src["title"],
             "repo": src["repo"], "repo_url": src["repo_url"],
             "branch": src["branch"], "path": src["path"],
             "matrix": src.get("matrix"), "versions": index_versions,
             "cycles": cycles, "releases": releases, "metrics": metrics,
             "features": features if src["kind"] == "conformance" else None}
    return put(out, base, "index", index)


def reset_out(out):
    """Remove stale hashed files; only ever touches `<out>/sources`."""
    shutil.rmtree(Path(out) / "sources", ignore_errors=True)
    Path(out).mkdir(parents=True, exist_ok=True)


def now_utc():
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    t = datetime.fromtimestamp(int(epoch), timezone.utc) if epoch else datetime.now(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def write_manifest(out, entries):
    manifest = {"format": FORMAT, "generated": now_utc(), "sources": entries}
    (Path(out) / "manifest.json").write_bytes(dumps(manifest))


def manifest_entry(src, index=None, reason=None):
    e = {"id": src["id"], "kind": src["kind"], "title": src["title"],
         "repo": src["repo"], "matrix": src.get("matrix")}
    if index:
        e.update(status="ok", index=index)
    else:
        e.update(status="unpublished", reason=reason)
    return e


# ------------------------------------------------------------------ collecting

def load_config(path):
    try:
        with open(path, "rb") as f:
            doc = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"{path}: {e}")
    repos = {}
    for r in doc.get("repo", []):
        for k in ("name", "url", "default_branch", "tag"):
            if k not in r:
                raise ConfigError(f"repo {r.get('name', '?')}: missing `{k}`")
        try:
            r["tag_re"] = re.compile(r["tag"])
        except re.error as e:
            raise ConfigError(f"repo {r['name']}: bad tag regex: {e}")
        if "version" not in r["tag_re"].groupindex:
            raise ConfigError(f"repo {r['name']}: tag regex needs a `version` group")
        if r["name"] in repos:
            raise ConfigError(f"duplicate repo {r['name']}")
        repos[r["name"]] = r
    sources, seen = [], set()
    for s in doc.get("source", []):
        for k in ("id", "kind", "title", "repo", "branch", "path"):
            if k not in s:
                raise ConfigError(f"source {s.get('id', '?')}: missing `{k}`")
        if not re.fullmatch(r"[a-z0-9-]+", s["id"]):
            raise ConfigError(f"source id {s['id']!r} must match [a-z0-9-]+")
        if s["id"] in seen:
            raise ConfigError(f"duplicate source id {s['id']}")
        seen.add(s["id"])
        if s["kind"] not in KINDS:
            raise ConfigError(f"source {s['id']}: unknown kind {s['kind']!r}")
        if s["repo"] not in repos:
            raise ConfigError(f"source {s['id']}: unknown repo {s['repo']!r}")
        if s["kind"] == "conformance" and s.get("matrix") not in MATRICES:
            raise ConfigError(f"source {s['id']}: `matrix` must be wire or codegen")
        f = s.get("features")
        if f is not None and (f.get("repo") not in repos or "path" not in f):
            raise ConfigError(f"source {s['id']}: bad `features`")
        sources.append(s)
    return repos, sources


class Collector:
    def __init__(self, repo_cfgs, cache, locals_):
        self.cfgs, self.cache, self.locals = repo_cfgs, cache, locals_
        self._repos, self._failed = {}, {}

    def repo(self, name):
        if name in self._failed:
            raise SourceError(self._failed[name])
        if name not in self._repos:
            cfg = self.cfgs[name]
            if name in self.locals:
                path = Path(self.locals[name])
                if not path.exists():
                    self._failed[name] = f"local checkout {path} not found"
                    raise SourceError(self._failed[name])
                self._repos[name] = Repo(cfg, path, writable=False)
            else:
                self._repos[name] = Repo(cfg, Path(self.cache) / name, writable=True)
        return self._repos[name]

    def features_for(self, src, versions_reports):
        spec = src.get("features")
        if spec:
            repo = self.repo(spec["repo"])
            branch = self.cfgs[spec["repo"]]["default_branch"]
            ref = repo.ref(branch)
            raw = repo.show(ref, spec["path"])
            if raw is None:
                raise SourceError(f"features file {spec['path']} not found on {branch}")
            try:
                return feature_map(json.loads(raw))
            except (ValueError, KeyError, TypeError) as e:
                raise SourceError(f"features file doesn't parse: {e}")
        if versions_reports:
            try:
                return feature_map(versions_reports[-1])
            except (ValueError, KeyError, TypeError):
                pass
        return {}

    def collect(self, src, out):
        """Publish one source; returns the index path or raises SourceError."""
        repo = self.repo(src["repo"])
        ref = repo.ref(src["branch"])
        commits = repo.history(ref, src["path"])
        if not commits:
            raise SourceError(f"path not found on branch {src['branch']}")
        versions, reports = [], []
        for h, date in commits:
            raw = repo.show(h, src["path"])
            if raw is None:  # the commit deleted the file
                continue
            try:
                rep = json.loads(raw)
                norm = NORMALISERS[src["kind"]](rep)
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                raise SourceError(f"report at {h[:10]} doesn't parse: {e}")
            measured = norm.commit or h
            full = repo.resolve_commit(measured)
            tag = None
            if full:
                measured = full
                tag = repo.cycle_tag(full)
            else:
                warn(f"{src['id']}: measured commit {measured[:12]} (version {h[:10]}) "
                     f"is not in {src['repo']}; counted as unreleased")
            versions.append(Version(h, measured, date, tag.version if tag else UNRELEASED, norm))
            reports.append(rep)
        if not versions:
            raise SourceError(f"path not found on branch {src['branch']}")
        order = sorted(range(len(versions)), key=lambda i: versions[i].date)  # stable
        versions = [versions[i] for i in order]
        reports = [reports[i] for i in order]
        features = self.features_for(src, reports) if src["kind"] == "conformance" else None
        tags = {t.version: t for t in repo.tags()}
        meta = dict(src, repo_url=self.cfgs[src["repo"]]["url"])
        return publish_source(out, meta, versions, tags, features)


def run(sources_path, out, cache, locals_, strict):
    repos, sources = load_config(sources_path)
    reset_out(out)
    col = Collector(repos, cache, locals_)
    entries, bad = [], 0
    for src in sources:
        try:
            entries.append(manifest_entry(src, index=col.collect(src, out)))
        except SourceError as e:
            bad += 1
            warn(f"{src['id']}: unpublished: {e}")
            entries.append(manifest_entry(src, reason=str(e)))
    write_manifest(out, entries)
    return 1 if strict and bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", default="sources.toml")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default=".cache/repos")
    ap.add_argument("--local", action="append", default=[], metavar="NAME=PATH")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)
    locals_ = {}
    for item in a.local:
        name, sep, path = item.partition("=")
        if not sep or not name or not path:
            ap.error(f"--local expects name=path, got {item!r}")
        locals_[name] = path
    try:
        return run(a.sources, a.out, a.cache, locals_, a.strict)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
