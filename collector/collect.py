#!/usr/bin/env python3
"""Observatory collector: reads report histories from git and writes the
dataset described in DATA.md.  Python 3.11+, standard library plus `git`."""

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

FORMAT = 1
KINDS = ("bench", "fuzz", "conformance", "size", "compile", "coverage", "ci")
CI_EVENTS = ("push", "schedule", "workflow_dispatch")
CI_LIMIT = 1000
MATRICES = ("wire", "codegen")
STATES = ("supported", "partial", "ignored", "unsupported")
UNRELEASED = "unreleased"
INT_RE = re.compile(r"^(0|[1-9][0-9]*)$")
PR_RE = re.compile(r"^Merge pull request #(\d+) |\(#(\d+)\)$")


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
            p = self.git("fetch", "--quiet", "origin",
                         f"+refs/heads/{branch}:refs/remotes/origin/{branch}", check=False)
            if p.returncode != 0:
                if b"couldn't find remote ref" in p.stderr:
                    raise SourceError(f"branch {branch} not found in {self.name}")
                self.git("fetch", "--quiet", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
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

    def contains(self, ancestor, commit):
        """Whether `commit`'s history contains `ancestor`."""
        p = self.git("merge-base", "--is-ancestor", ancestor, commit, check=False)
        if p.returncode not in (0, 1):
            raise SourceError(f"git merge-base failed in {self.name}")
        return p.returncode == 0

    def pr_commits(self, ref):
        """{pull request number: the first-parent commit that merged it} on `ref`,
        from "Merge pull request #N" or a trailing "(#N)" in the subject."""
        out = self.git("log", "--first-parent", "--format=%H%x09%s", ref).stdout.decode()
        res = {}
        for line in out.splitlines():
            h, _, subj = line.partition("\t")
            m = PR_RE.search(subj)
            if m:
                res.setdefault(int(m.group(1) or m.group(2)), h)
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


def _obj(rep):
    if not isinstance(rep, dict):
        raise ValueError("not an object")
    return rep


def _envelope(rep):
    return (_str_or_none(rep.get("commit")), _str_or_none(rep.get("toolchain")),
            _str_or_none(rep.get("run")))


def normalise_size(rep):
    rep = _obj(rep)
    if not isinstance(rep.get("artifacts"), dict):
        raise ValueError("no `artifacts` object")
    rows, shard = {}, {}
    for aid, a in rep["artifacts"].items():
        if not isinstance(a, dict):
            raise ValueError(f"artifact {aid} is not an object")
        shard[aid] = {"bytes": _num(a.get("bytes")), "gzip_bytes": _num(a.get("gzip_bytes"))}
        rows[(aid, "bytes")] = (shard[aid]["bytes"], "bytes", "number")
        if "gzip_bytes" in a:
            rows[(aid, "gzip_bytes")] = (shard[aid]["gzip_bytes"], "bytes", "number")
    return Norm(rows, {"artifacts": shard}, *_envelope(rep))


def normalise_compile(rep):
    rep = _obj(rep)
    if not isinstance(rep.get("units"), dict):
        raise ValueError("no `units` object")
    runner = rep.get("runner")
    metric = "seconds" if runner in (None, "") else f"seconds@{runner}"
    rows = {}
    for crate, u in rep["units"].items():
        rows[(crate, metric)] = (_num(u.get("seconds")) if isinstance(u, dict) else None, "s", "number")
    rows[("total", metric)] = (_num(rep.get("total_seconds")), "s", "number")
    shard = {k: v for k, v in rep.items() if k not in ("format", "commit", "toolchain", "run")}
    return Norm(rows, shard, *_envelope(rep))


COVERAGE_METRICS = ("lines", "functions", "branches")


def _counts(c):
    if not isinstance(c, dict):
        raise ValueError("coverage entry is not an object")
    out = {}
    for m in COVERAGE_METRICS:
        v = c.get(m)
        if isinstance(v, dict):
            out[m] = {"covered": _num(v.get("covered")), "total": _num(v.get("total"))}
    if not out:
        raise ValueError("coverage entry has no counts")
    return out


def normalise_coverage(rep):
    rep = _obj(rep)
    if not isinstance(rep.get("totals"), dict):
        raise ValueError("no `totals` object")
    totals = _counts(rep["totals"])
    units = {u: _counts(c) for u, c in (rep.get("units") or {}).items()}
    rows = {}
    for key, c in [("total", totals), *units.items()]:
        for m, v in c.items():
            cov, tot = v["covered"], v["total"]
            pct = round(cov / tot * 100, 2) if cov is not None and tot else None
            rows[(key, m)] = (pct, "%", "number")
    return Norm(rows, {"totals": totals, "units": units}, *_envelope(rep))


NORMALISERS = {"bench": normalise_bench, "fuzz": normalise_fuzz,
               "conformance": normalise_conformance, "size": normalise_size,
               "compile": normalise_compile, "coverage": normalise_coverage}


def better(kind, metric, typ):
    """Which way is an improvement: "higher", "lower", or None (no direction)."""
    if typ in ("verdict", "state"):
        return None
    if kind == "coverage" or (kind == "fuzz" and metric in ("executions", "corpus")):
        return "higher"
    return "lower"


# --------------------------------------------------------------------- ci

def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def normalise_run(run):
    """One workflow run (GitHub API shape) as a Norm."""
    name = run.get("name") or "workflow"
    started = run.get("run_started_at") or run.get("created_at")
    dur = None
    if started and run.get("updated_at"):
        dur = max(0, int((_ts(run["updated_at"]) - _ts(started)).total_seconds()))
    concl = run.get("conclusion")
    verdict = "pass" if concl == "success" else "fail" if concl in ("failure", "timed_out") else None
    attempt = run.get("run_attempt")
    rows = {(name, "duration_s"): (dur, "s", "number"),
            (name, "attempts"): (attempt, None, "number"),
            (name, "conclusion"): (verdict, None, "verdict")}
    shard = {"workflow": name, "event": run.get("event"), "conclusion": concl,
             "run_attempt": attempt, "duration_s": dur, "html_url": run.get("html_url")}
    return Norm(rows, shard, run.get("head_sha"), None, run.get("html_url"))


def github_slug(url):
    m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not m:
        raise SourceError(f"not a GitHub url: {url}")
    return m.group(1)


def fetch_runs(slug, branch, token):
    """Newest completed runs on `branch` for CI_EVENTS, at most CI_LIMIT, as
    the API's dicts.  Raises SourceError on any failure."""
    runs = {}
    for event in CI_EVENTS:
        for page in range(1, CI_LIMIT // 100 + 1):
            url = (f"https://api.github.com/repos/{slug}/actions/runs?status=completed"
                   f"&branch={branch}&event={event}&per_page=100&page={page}")
            headers = {"Accept": "application/vnd.github+json",
                       "User-Agent": "comline-observatory",
                       "X-GitHub-Api-Version": "2022-11-28"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                    doc = json.load(r)
            except urllib.error.HTTPError as e:
                hint = " (rate limited; set GITHUB_TOKEN)" if e.code in (403, 429) else ""
                raise SourceError(f"GitHub API {e.code} for {slug}{hint}")
            except (urllib.error.URLError, OSError, ValueError) as e:
                raise SourceError(f"GitHub API unreachable for {slug}: {e}")
            batch = doc.get("workflow_runs") or []
            for r in batch:
                runs[r["id"]] = r
            if len(batch) < 100:
                break
    newest = sorted(runs.values(), key=lambda r: (r.get("created_at") or "", r["id"]), reverse=True)
    return newest[:CI_LIMIT]


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


def normalise_ledger(doc):
    """The accepted-regressions ledger's entries, without their version."""
    if not isinstance(doc, dict):
        raise ValueError("not a table")
    out = []
    for kind in ("accepted", "removed"):
        entries = doc.get(kind, [])
        if not isinstance(entries, list):
            raise ValueError(f"`{kind}` is not an array of tables")
        for e in entries:
            if not isinstance(e, dict) or not isinstance(e.get("bench"), str) \
                    or not isinstance(e.get("pr"), int) or isinstance(e.get("pr"), bool):
                raise ValueError(f"a [[{kind}]] entry without `pr` or `bench`")
            out.append({"kind": kind, "pr": e["pr"], "bench": e["bench"],
                        "max_percent": _num(e.get("max_percent")) if kind == "accepted" else None,
                        "renamed_to": _str_or_none(e.get("renamed_to")) if kind == "removed" else None,
                        "reason": _str_or_none(e.get("reason"))})
    return out


def publish_source(out, src, versions, tags, features, ledger=None):
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
                        "group": group, "param": param,
                        "better": better(src["kind"], metric, typ)})

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
             "features": features if src["kind"] == "conformance" else None,
             "ledger": ledger}
    return put(out, base, "index", index)


def reset_out(out):
    """Remove stale hashed files; only ever touches `<out>/sources`."""
    shutil.rmtree(Path(out) / "sources", ignore_errors=True)
    Path(out).mkdir(parents=True, exist_ok=True)


def now_utc():
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    t = datetime.fromtimestamp(int(epoch), timezone.utc) if epoch else datetime.now(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


SPARK_POINTS = 40


def lttb(ys, n=SPARK_POINTS):
    """Largest-triangle-three-buckets: `ys` (numbers or None) down to at most
    `n` values. A series that already fits is returned unchanged (gaps kept);
    a longer one is reduced over its non-null points, gaps dropped."""
    if len(ys) <= n:
        return list(ys)
    pts = [(i, y) for i, y in enumerate(ys) if y is not None]
    if len(pts) <= n:
        return [y for _, y in pts]
    out = [pts[0]]
    every = (len(pts) - 2) / (n - 2)
    a = 0
    for i in range(n - 2):
        lo, hi = int((i + 1) * every) + 1, min(int((i + 2) * every) + 1, len(pts))
        nxt = pts[lo:hi] or [pts[-1]]
        cx = sum(p[0] for p in nxt) / len(nxt)
        cy = sum(p[1] for p in nxt) / len(nxt)
        blo, bhi = int(i * every) + 1, int((i + 1) * every) + 1
        ax, ay = pts[a]
        best, best_area = blo, -1.0
        for j in range(blo, bhi):
            area = abs((ax - cx) * (pts[j][1] - ay) - (ax - pts[j][0]) * (cy - ay))
            if area > best_area:
                best, best_area = j, area
        out.append(pts[best])
        a = best
    out.append(pts[-1])
    return [y for _, y in out]


def fmt_unit(v, unit):
    """The site's fmtUnit (en-US, at most 2 decimals), for the card badges."""
    if v is None:
        return "\u2013"

    def num(x):
        return f"{Decimal(str(x)).quantize(Decimal('0.01'), ROUND_HALF_UP):,}".rstrip("0").rstrip(".")
    if unit == "bytes":
        a = abs(v)
        d, u = (1e9, "GB") if a >= 1e9 else (1e6, "MB") if a >= 1e6 else (1e3, "KB") if a >= 1e3 else (1, "B")
        return f"{num(v / d)} {u}"
    if unit == "s":
        return f"{num(v)} s"
    if unit == "%":
        return f"{num(v)}%"
    return f"{v:,}"


def _sum_at(cols, metrics, vs, pick):
    out = []
    for v in vs:
        xs = [cols[i].get(v) for i, m in enumerate(metrics) if pick(m)]
        xs = [x for x in xs if isinstance(x, (int, float))]
        out.append(sum(xs) if xs else None)
    return out


def card_summary(index, cols):
    """What the site's source card shows: latest version, a sparkline over the
    newest cycle and a status line. `cols[i]` maps version index to the value
    of `index["metrics"][i]` (the newest cycle's chunk)."""
    vers, ms = index["versions"], index["metrics"]
    newest = index["cycles"][-1]["id"]
    vs = [i for i, v in enumerate(vers) if v["cycle"] == newest]
    hi, last = vs[-1], len(vers) - 1
    kind = index["kind"]
    badge = None
    row = lambda key, metric: next((i for i, m in enumerate(ms) if m["key"] == key and m["metric"] == metric), -1)  # noqa: E731
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)  # noqa: E731

    if kind == "bench":
        label = "geometric mean, relative to the newest version"
        spark = []
        for v in vs:
            tot, n = 0.0, 0
            for i in range(len(ms)):
                b, x = cols[i].get(hi), cols[i].get(v)
                if num(b) and num(x) and b > 0 and x > 0:
                    tot += math.log(x / b)
                    n += 1
            spark.append(math.exp(tot / n) if n else None)
    elif kind == "fuzz":
        label = "total executions"
        spark = _sum_at(cols, ms, vs, lambda m: m["metric"] == "executions")
        findings = fails = 0
        for i, m in enumerate(ms):
            x = cols[i].get(last)
            if m["metric"] == "findings" and num(x):
                findings += x
            if m["type"] == "verdict" and x == "fail":
                fails += 1
        badge = ({"text": f"{findings} findings, {fails} failing properties", "cls": "s-fail"}
                 if findings or fails else {"text": "no findings, all properties pass", "cls": "s-pass"})
    elif kind == "size":
        label = "total bytes, all artifacts"
        spark = _sum_at(cols, ms, vs, lambda m: m["metric"] == "bytes")
        t = _sum_at(cols, ms, [last], lambda m: m["metric"] == "bytes")[0]
        badge = {"text": f"{fmt_unit(t, 'bytes')} in {len({m['key'] for m in ms})} artifacts", "cls": ""}
    elif kind == "compile":
        r = next((i for i, m in enumerate(ms) if m["key"] == "total"), -1)
        label = "total build time"
        spark = [cols[r].get(v) if r >= 0 else None for v in vs]
        if r >= 0:
            badge = {"text": f"{fmt_unit(cols[r].get(last), 's')} clean build", "cls": ""}
    elif kind == "coverage":
        r = row("total", "lines")
        label = "total line coverage"
        spark = [cols[r].get(v) if r >= 0 else None for v in vs]
        if r >= 0:
            badge = {"text": f"{fmt_unit(cols[r].get(last), '%')} of lines covered", "cls": ""}
    elif kind == "ci":
        verdicts = [i for i, m in enumerate(ms) if m["metric"] == "conclusion"]
        W = 10
        seq = []
        for v in vs:
            seq.append(next((x for x in (cols[i].get(v) for i in verdicts) if x in ("pass", "fail")), None))
        label = f"pass rate, last {W} runs"
        spark = []
        for k in range(len(seq)):
            w = [x for x in seq[max(0, k - W + 1):k + 1] if x]
            spark.append(sum(x == "pass" for x in w) / len(w) * 100 if w else None)
        judged = [x for x in seq if x]
        passed = sum(x == "pass" for x in judged)
        rate = passed / len(judged) * 100 if judged else None
        rate_txt = "\u2013" if rate is None else f"{Decimal(rate).quantize(Decimal('1'), ROUND_HALF_UP)}%"
        badge = {"text": f"{rate_txt} of {len(judged)} runs passed",
                 "cls": "s-fail" if rate is not None and rate < 90 else "s-pass"}
    else:
        label = "supported cells"
        spark = [sum(cols[i].get(v) == "supported" for i in range(len(ms))) for v in vs]
        counts = {}
        for i in range(len(ms)):
            x = cols[i].get(last)
            if isinstance(x, str):
                counts[x] = counts.get(x, 0) + 1
        badge = {"text": ", ".join(f"{counts[k]} {k}" for k in ("supported", "partial", "ignored", "unsupported") if counts.get(k)),
                 "cls": "s-partial" if counts.get("unsupported") else "s-supported"}

    lv = vers[last]
    return {"label": lv["label"], "date": lv["date"], "release": lv["release"],
            "spark": [None if y is None else round(y, 6) for y in lttb(spark)],
            "sparkLabel": label, "badge": badge}


def write_summary(out, entries):
    """One small file with every ok source's card; returns its relative path."""
    cards = {}
    for e in entries:
        if e["status"] != "ok":
            continue
        index = json.loads((Path(out) / e["index"]).read_text())
        chunk = json.loads((Path(out) / index["cycles"][-1]["chunk"]).read_text())
        cols = [dict(zip(chunk["versions"], row)) for row in chunk["values"]]
        cards[e["id"]] = card_summary(index, cols)
    return put(out, "sources", "summary", {"sources": cards})


def write_manifest(out, entries):
    manifest = {"format": FORMAT, "generated": now_utc(), "sources": entries,
                "summary": write_summary(out, entries)}
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
        need = ("id", "kind", "title", "repo") if s.get("kind") == "ci" else \
            ("id", "kind", "title", "repo", "branch", "path")
        for k in need:
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
        if "ledger" in s and (s["kind"] != "bench" or not isinstance(s["ledger"], str)):
            raise ConfigError(f"source {s['id']}: `ledger` is a path, on bench sources only")
        f = s.get("features")
        if f is not None and (f.get("repo") not in repos or "path" not in f):
            raise ConfigError(f"source {s['id']}: bad `features`")
        if s["kind"] == "ci":
            s["branch"], s["path"] = repos[s["repo"]]["default_branch"], None
        sources.append(s)
    return repos, sources


class Collector:
    def __init__(self, repo_cfgs, cache, locals_, network=True):
        self.cfgs, self.cache, self.locals = repo_cfgs, cache, locals_
        self.network = network
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

    def ledger_for(self, src, versions):
        """The source's ledger (DATA.md), each entry with the index of the first
        version whose measured commit contains the pull request; None when the
        source has no `ledger`."""
        if "ledger" not in src:
            return None
        repo = self.repo(src["repo"])
        branch = self.cfgs[src["repo"]]["default_branch"]
        ref = repo.ref(branch)
        raw = repo.show(ref, src["ledger"])
        if raw is None:
            warn(f"{src['id']}: ledger {src['ledger']} not found on {branch}")
            return []
        try:
            entries = normalise_ledger(tomllib.loads(raw.decode("utf-8")))
        except (ValueError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
            warn(f"{src['id']}: ledger doesn't parse: {e}")
            return []
        prs = repo.pr_commits(ref)
        for e in entries:
            e["version"] = None
            merged = prs.get(e["pr"])
            if merged is None:
                continue
            for i, v in enumerate(versions):
                if repo.resolve_commit(v.commit) and repo.contains(merged, v.commit):
                    e["version"] = i
                    break
        return entries

    def collect_ci(self, src, out):
        if not self.network:
            raise SourceError("ci needs the network (--no-network)")
        cfg = self.cfgs[src["repo"]]
        slug = github_slug(cfg["url"])
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        runs = fetch_runs(slug, cfg["default_branch"], token)
        if not runs:
            raise SourceError("no completed runs on the default branch")
        repo = self.repo(src["repo"])
        repo.ref(cfg["default_branch"])  # fetches tags and the branch in a cache clone
        has_tags = bool(repo.tags())
        versions, missing = [], 0
        for r in reversed(runs):  # the API is newest first; walk oldest first
            norm = normalise_run(r)
            full = repo.resolve_commit(norm.commit)
            tag = None
            if full:
                norm.commit = full
                tag = repo.cycle_tag(full) if has_tags else None
            else:
                missing += 1
            started = r.get("run_started_at") or r.get("created_at")
            versions.append(Version(f"run-{r['id']}", norm.commit or "", utc(started),
                                    tag.version if tag else UNRELEASED, norm))
        if missing:
            warn(f"{src['id']}: {missing} runs measured commits not in {src['repo']}; counted as unreleased")
        versions.sort(key=lambda v: v.date)  # stable
        tags = {t.version: t for t in repo.tags()}
        meta = dict(src, repo_url=cfg["url"])
        return publish_source(out, meta, versions, tags, None)

    def collect(self, src, out):
        """Publish one source; returns the index path or raises SourceError."""
        if src["kind"] == "ci":
            return self.collect_ci(src, out)
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
        ledger = self.ledger_for(src, versions) if src["kind"] == "bench" else None
        tags = {t.version: t for t in repo.tags()}
        meta = dict(src, repo_url=self.cfgs[src["repo"]]["url"])
        return publish_source(out, meta, versions, tags, features, ledger)


def run(sources_path, out, cache, locals_, strict, network=True):
    repos, sources = load_config(sources_path)
    reset_out(out)
    col = Collector(repos, cache, locals_, network)
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
    ap.add_argument("--no-network", action="store_true",
                    help="don't call the GitHub API: ci sources are unpublished")
    a = ap.parse_args(argv)
    locals_ = {}
    for item in a.local:
        name, sep, path = item.partition("=")
        if not sep or not name or not path:
            ap.error(f"--local expects name=path, got {item!r}")
        locals_[name] = path
    try:
        return run(a.sources, a.out, a.cache, locals_, a.strict, not a.no_network)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
