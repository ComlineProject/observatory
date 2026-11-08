#!/usr/bin/env python3
"""Write a `size` report (DATA.md): bytes and gzip -9 bytes per artifact.
`commit` is $GITHUB_SHA, `run` the workflow run's URL.  Standard library only."""

import argparse
import glob
import gzip
import json
import os
import sys
from pathlib import Path


def run_url(env=os.environ):
    if env.get("GITHUB_RUN_ID") and env.get("GITHUB_REPOSITORY"):
        return f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/" \
               f"{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
    return None


def parse_artifacts(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        aid, sep, pattern = line.partition("=")
        aid, pattern = aid.strip(), pattern.strip()
        if not sep or not aid or not pattern:
            raise SystemExit(f"error: expected `id=path`, got {line!r}")
        if aid in out:
            raise SystemExit(f"error: duplicate artifact id {aid}")
        matches = sorted(glob.glob(pattern))
        if len(matches) != 1:
            raise SystemExit(f"error: {aid}: {pattern!r} matches {len(matches)} files, expected exactly one")
        out[aid] = matches[0]
    if not out:
        raise SystemExit("error: no artifacts given")
    return out


def build(artifacts, commit, run, toolchain):
    sizes = {}
    for aid, path in artifacts.items():
        data = Path(path).read_bytes()
        sizes[aid] = {"bytes": len(data), "gzip_bytes": len(gzip.compress(data, 9, mtime=0))}
    return {"format": 1, "commit": commit, "toolchain": toolchain or None, "run": run,
            "artifacts": sizes}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--output", required=True)
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--toolchain", default="")
    a = ap.parse_args(argv)
    report = build(parse_artifacts(a.artifacts), os.environ.get("GITHUB_SHA"), run_url(), a.toolchain)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}: " + ", ".join(f"{k} {v['bytes']}B" for k, v in report["artifacts"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
