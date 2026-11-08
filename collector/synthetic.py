#!/usr/bin/env python3
"""Write a synthetic dataset in the real format, for the site's performance
budget.  `--scale N` multiplies both versions and metrics by N.  Reports are
generated in the collector's input shapes and pushed through its own
normalisers and writers, so the format can't drift."""

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone

import collect

START = datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
RELEASES = ("0.1.0", "0.2.0", "0.3.0")  # then unreleased


class SynTag:
    def __init__(self, version, date):
        self.version, self.name, self.date = version, f"v{version}", date


def timeline(n, step_hours, rng):
    """n (id, commit, date, cycle) rows: three released cycles then unreleased."""
    dates, t = [], START
    for _ in range(n):
        t += timedelta(hours=step_hours * (0.5 + rng.random()))
        dates.append(t)
    bounds = [max(1, n * 3 // 10), max(2, n * 5 // 10), max(3, n * 7 // 10)]
    tags = {}
    for k, v in enumerate(RELEASES):
        tags[v] = SynTag(v, collect.utc((dates[min(bounds[k], n) - 1] + timedelta(minutes=5)).isoformat()))
    rows = []
    for i, d in enumerate(dates):
        cycle = next((RELEASES[k] for k in range(3) if i < bounds[k]), collect.UNRELEASED)
        rows.append((f"{rng.getrandbits(160):040x}", f"{rng.getrandbits(160):040x}",
                     collect.utc(d.isoformat()), cycle))
    return rows, tags


def build(out, scale, seed=7):
    rng = random.Random(seed)
    collect.reset_out(out)
    entries = []

    def emit(src, rows, tags, make_report, features=None):
        versions = []
        for i, (vid, commit, date, cycle) in enumerate(rows):
            rep = make_report(i, commit, date)
            norm = (collect.normalise_run if src["kind"] == "ci"
                    else collect.NORMALISERS[src["kind"]])(rep)
            norm.commit = commit
            versions.append(collect.Version(vid, commit, date, cycle, norm))
        src = dict(src, repo_url=f"https://example.invalid/{src['repo']}", path="report.json")
        entries.append(collect.manifest_entry(
            src, index=collect.publish_source(out, src, versions, tags, features)))

    # bench: ~170 metrics x ~50 versions; every third family is a payload-size one
    rows, tags = timeline(50 * scale, 8, rng)
    sizes = (16, 256, 4096)
    ids = [f"suite{m // 18}/bench{(m % 18) // 3}/{sizes[m % 3]}" for m in range(170 * scale)]
    base = [rng.randint(300, 90000) for _ in ids]
    born = [0 if rng.random() < 0.85 else rng.randrange(len(rows)) for _ in ids]

    def bench(i, commit, date):
        benches = {}
        for m, bid in enumerate(ids):
            if i >= born[m]:
                # Instruction counts are deterministic: they move in steps when
                # the code changes. The runtime's history moves ~7% of values
                # per version; 10% keeps the budget test a little pessimistic.
                if rng.random() < 0.10:
                    base[m] = max(10, int(base[m] * (1 + rng.uniform(-0.02, 0.025))))
                benches[bid] = {"ir": base[m]}
        return {"commit": commit, "toolchain": "rustc 1.98.0 (synthetic)", "benches": benches}

    emit({"id": "syn-bench", "kind": "bench", "title": "Synthetic bench", "repo": "syn",
          "branch": "reports"}, rows, tags, bench)

    # fuzz: ~7 targets + 8 properties x ~15 versions
    rows, tags = timeline(15 * scale, 24, rng)
    targets = [f"target_{t}" for t in range(7 * scale)]
    props = [f"property_{p}" for p in range(8 * scale)]

    def fuzz(i, commit, date):
        t = {}
        for name in targets:
            if rng.random() < 0.03:
                t[name] = {"error": "build failed"}
            else:
                t[name] = {"seconds": 601, "executions": rng.randint(10**6, 10**8),
                           "corpus": rng.randint(40, 40000), "findings": int(rng.random() < 0.02)}
        return {"commit": commit, "toolchain": "nightly (synthetic)", "date": date, "run": None,
                "targets": t,
                "proptest": {"cases": 100000, "properties": {
                    p: ("fail" if rng.random() < 0.03 else "pass") for p in props}}}

    emit({"id": "syn-fuzz", "kind": "fuzz", "title": "Synthetic fuzz", "repo": "syn",
          "branch": "reports"}, rows, tags, fuzz)

    # conformance: two wire sources (1 subject) and one codegen (2 subjects)
    states = ["supported"] * 8 + ["partial", "ignored", "unsupported"]
    feats = [f"feature-{f}" for f in range(20 * scale)]
    features = {f: {"title": f.replace("-", " "), "description": f"synthetic {f}"} for f in feats}

    def conformance(subjects):
        cur = {s: {f: rng.choice(states) for f in feats} for s in subjects}

        def make(i, commit, date):
            for s in subjects:
                for f in feats:
                    if rng.random() < 0.01:
                        cur[s][f] = rng.choice(states)
            return {"generators": [{"name": s, "support": {
                f: {"state": cur[s][f], "proven_by": [f"{f}/b", f"{f}/a"], "note": None}
                for f in feats}} for s in subjects]}
        return make

    for sid, title, subjects, matrix in (
            ("syn-wire-a", "Synthetic runtime A", ["a"], "wire"),
            ("syn-wire-b", "Synthetic runtime B", ["b"], "wire"),
            ("syn-codegen", "Synthetic generators", ["rust", "typescript"], "codegen")):
        rows, tags = timeline(20 * scale, 20, rng)
        emit({"id": sid, "kind": "conformance", "title": title, "repo": "syn",
              "branch": "main", "matrix": matrix}, rows, tags, conformance(subjects), features)

    # A second bench source (a "TypeScript" runtime): ~60% of syn-bench's keys at 2-8x
    # their values, plus keys of its own, over fewer versions. Drawn last so the
    # other sources' data doesn't move.
    rows, tags = timeline(max(3, 20 * scale), 16, rng)
    shared = [m for m in range(len(ids)) if rng.random() < 0.6]
    factor = {m: rng.uniform(2, 8) for m in shared}
    own = [f"ts{m // 6}/own{m % 6}/{sizes[m % 3]}" for m in range(max(10, 40 * scale))]
    own_base = [rng.randint(500, 400000) for _ in own]

    ts_base = {ids[m]: int(base[m] * factor[m]) for m in shared}
    ts_base.update(zip(own, own_base))
    # Format 2: the interpreter-only count and the optimising tier's (cheaper).
    opt = {name: rng.uniform(0.2, 0.5) for name in ts_base}

    def bench_ts(i, commit, date):
        # Like the Rust one, counts move in steps, a tenth of them per version.
        benches = {}
        for name, v in ts_base.items():
            if rng.random() < 0.10:
                v = ts_base[name] = max(10, int(v * (1 + rng.uniform(-0.02, 0.025))))
            benches[name] = {"instructions": {"value": v},
                             "instructions-opt": {"value": max(10, int(v * opt[name]))}}
        return {"commit": commit, "toolchain": "node 22 (synthetic)", "benches": benches}

    emit({"id": "syn-bench-ts", "kind": "bench", "title": "Synthetic TS bench", "repo": "syn",
          "branch": "reports"}, rows, tags, bench_ts)

    # size / compile / coverage / ci, drawn after everything else so the
    # sources above don't move.
    rows, tags = timeline(40 * scale, 12, rng)
    arts = [f"{p}/{t}" for p in ("ffi", "cli", "wasm", "lib")[:4]
            for t in ("x86_64-linux-release", "aarch64-linux-release", "wasm32-release")]
    arts = (arts * scale)[:12 * scale] if scale == 1 else \
        [f"{a}/v{k}" for k in range(scale) for a in arts]
    sz = {a: rng.randint(200_000, 9_000_000) for a in arts}

    def size(i, commit, date):
        for a in arts:
            if rng.random() < 0.2:
                sz[a] = max(1000, int(sz[a] * (1 + rng.uniform(-0.03, 0.04))))
        return {"commit": commit, "toolchain": "rustc 1.98.0 (synthetic)", "run": None,
                "artifacts": {a: {"bytes": v, "gzip_bytes": int(v * 0.38)} for a, v in sz.items()}}

    emit({"id": "syn-size", "kind": "size", "title": "Synthetic size", "repo": "syn",
          "branch": "reports"}, rows, tags, size)

    rows, tags = timeline(30 * scale, 14, rng)
    crates = [f"crate-{c}" for c in range(15 * scale)]
    ct = {c: rng.uniform(1, 40) for c in crates}

    def compile_(i, commit, date):
        for c in crates:
            ct[c] = max(0.2, ct[c] * (1 + rng.uniform(-0.15, 0.15)))
        return {"commit": commit, "toolchain": "nightly (synthetic)", "run": None,
                "runner": "github-hosted", "profile": "release",
                "total_seconds": sum(ct.values()) * 0.7,
                "units": {c: {"seconds": round(v, 2)} for c, v in ct.items()}}

    emit({"id": "syn-compile", "kind": "compile", "title": "Synthetic compile", "repo": "syn",
          "branch": "reports"}, rows, tags, compile_)

    rows, tags = timeline(30 * scale, 14, rng)
    units = [f"unit-{u}" for u in range(10 * scale)]
    tot = {u: rng.randint(200, 5000) for u in units}
    cov = {u: rng.uniform(0.5, 0.95) for u in units}

    def coverage(i, commit, date):
        def c(u):
            return {k: {"covered": int(tot[u] * f * cov[u]), "total": int(tot[u] * f)}
                    for k, f in (("lines", 1), ("functions", 0.1), ("branches", 0.3))}
        for u in units:
            cov[u] = min(0.99, max(0.2, cov[u] + rng.uniform(-0.02, 0.02)))
        per = {u: c(u) for u in units}
        return {"commit": commit, "toolchain": "nightly (synthetic)", "run": None,
                "tool": "cargo-llvm-cov",
                "totals": {k: {"covered": sum(per[u][k]["covered"] for u in units),
                               "total": sum(per[u][k]["total"] for u in units)}
                           for k in ("lines", "functions", "branches")},
                "units": per}

    emit({"id": "syn-coverage", "kind": "coverage", "title": "Synthetic coverage", "repo": "syn",
          "branch": "reports"}, rows, tags, coverage)

    # ci: one version per run, each with a single workflow's values
    rows, tags = timeline(300 * scale, 3, rng)
    flows = [("ci", "push"), ("lint", "push"), ("fuzz", "schedule"), ("bench", "schedule"),
             ("docs", "push"), ("release", "workflow_dispatch")]

    def ci(i, commit, date):
        name, event = flows[i % len(flows)]
        start = datetime.fromisoformat(date.replace("Z", "+00:00"))
        secs = int(rng.uniform(60, 900) * (3 if name == "fuzz" else 1))
        end = start + timedelta(seconds=secs)
        failed = rng.random() < 0.08
        return {"id": 10_000 + i, "name": name, "head_sha": commit, "event": event,
                "conclusion": "failure" if failed else "success",
                "run_attempt": 2 if rng.random() < 0.05 else 1,
                "run_started_at": date, "created_at": date,
                "updated_at": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "html_url": f"https://example.invalid/runs/{10_000 + i}"}

    emit({"id": "syn-ci", "kind": "ci", "title": "Synthetic CI", "repo": "syn",
          "branch": "main"}, rows, tags, ci)

    collect.write_manifest(out, entries)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.scale < 1:
        ap.error("--scale must be >= 1")
    build(a.out, a.scale)
    return 0


if __name__ == "__main__":
    sys.exit(main())
