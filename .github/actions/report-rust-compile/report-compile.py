#!/usr/bin/env python3
"""Turn cargo's `--timings` report into a `compile` report (DATA.md).  The HTML
report embeds `const UNIT_DATA = [...]` (one entry per compiled unit, with
`name`, `start`, `duration` in seconds); durations are summed per workspace
crate (build scripts included) and the total is the end of the last unit.
Standard library only."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def run_url(env=os.environ):
    if env.get("GITHUB_RUN_ID") and env.get("GITHUB_REPOSITORY"):
        return f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/" \
               f"{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
    return None


def unit_data(html):
    m = re.search(r"^const UNIT_DATA = (\[.*?^\]);?$", html, re.S | re.M)
    if not m:
        raise SystemExit("error: no UNIT_DATA in the timing report; has cargo's format changed?")
    return json.loads(m.group(1))


def convert(units, members, commit, toolchain, run, runner, profile):
    secs = {}
    for u in units:
        if u["name"] in members:
            secs[u["name"]] = secs.get(u["name"], 0) + u["duration"]
    if not units:
        raise SystemExit("error: the timing report has no units (nothing was rebuilt?)")
    total = max(u["start"] + u["duration"] for u in units)
    return {"format": 1, "commit": commit, "toolchain": toolchain or None, "run": run,
            "runner": runner, "profile": profile, "total_seconds": round(total, 2),
            "units": {k: {"seconds": round(v, 2)} for k, v in sorted(secs.items())}}


def profile_of(args):
    toks = args.split()
    for i, t in enumerate(toks):
        if t == "--release":
            return "release"
        if t == "--profile" and i + 1 < len(toks):
            return toks[i + 1]
        if t.startswith("--profile="):
            return t.split("=", 1)[1]
    return "dev"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", required=True)
    ap.add_argument("--runner", default="github-hosted")
    ap.add_argument("--profile", default="--release", help="the cargo build arguments")
    ap.add_argument("--toolchain", default="")
    ap.add_argument("--timings", help="the report to read (default: the target dir's latest)")
    a = ap.parse_args(argv)
    meta = json.loads(subprocess.run(["cargo", "metadata", "--no-deps", "--format-version", "1"],
                                     capture_output=True, text=True, check=True).stdout)
    members = {p["name"] for p in meta["packages"]}
    html_path = Path(a.timings) if a.timings else Path(meta["target_directory"]) / "cargo-timings" / "cargo-timing.html"
    report = convert(unit_data(html_path.read_text()), members, os.environ.get("GITHUB_SHA"),
                     a.toolchain, run_url(), a.runner, profile_of(a.profile))
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}: {len(report['units'])} crates, {report['total_seconds']}s total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
