#!/usr/bin/env python3
"""Convert `cargo llvm-cov --json --summary-only` output into a `coverage`
report (DATA.md): units are the workspace's crates, found with `cargo
metadata`.  Standard library only."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

KEYS = ("lines", "functions", "branches")


def run_url(env=os.environ):
    if env.get("GITHUB_RUN_ID") and env.get("GITHUB_REPOSITORY"):
        return f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/" \
               f"{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
    return None


def counts(summary, with_branches):
    out = {}
    for k in KEYS:
        v = summary.get(k)
        if isinstance(v, dict) and "covered" in v and "count" in v and (k != "branches" or with_branches):
            out[k] = {"covered": v["covered"], "total": v["count"]}
    return out


def crate_of(filename, packages):
    """The package whose directory contains `filename` (the deepest wins)."""
    best = None
    for name, d in packages:
        if filename.startswith(d.rstrip("/") + "/") and (best is None or len(d) > len(best[1])):
            best = (name, d)
    return best[0] if best else None


def convert(llvm, packages, commit, toolchain, run, tool):
    data = llvm["data"][0]
    totals = data["totals"]
    with_branches = bool(totals.get("branches", {}).get("count"))
    units = {}
    for f in data.get("files", []):
        crate = crate_of(f["filename"], packages)
        if crate is None:
            continue
        u = units.setdefault(crate, {k: {"covered": 0, "total": 0} for k in KEYS})
        for k, v in counts(f["summary"], with_branches).items():
            u[k]["covered"] += v["covered"]
            u[k]["total"] += v["total"]
    for u in units.values():
        for k in [k for k in u if k == "branches" and not with_branches]:
            del u[k]
    return {"format": 1, "commit": commit, "toolchain": toolchain or None, "run": run,
            "tool": tool or "cargo-llvm-cov", "totals": counts(totals, with_branches),
            "units": dict(sorted(units.items()))}


def workspace_packages():
    p = subprocess.run(["cargo", "metadata", "--no-deps", "--format-version", "1"],
                       capture_output=True, text=True, check=True)
    return [(pkg["name"], str(Path(pkg["manifest_path"]).parent))
            for pkg in json.loads(p.stdout)["packages"]]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--tool", default="")
    ap.add_argument("--toolchain", default="")
    a = ap.parse_args(argv)
    llvm = json.loads(Path(a.input).read_text())
    report = convert(llvm, workspace_packages(), os.environ.get("GITHUB_SHA"), a.toolchain,
                     run_url(), a.tool)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    t = report["totals"].get("lines", {})
    print(f"wrote {out}: {len(report['units'])} crates, lines {t.get('covered')}/{t.get('total')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
