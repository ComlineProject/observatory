# Data contract

The collector (`collector/collect.py`) writes this; the site (`site/`) reads
it. Nothing else is shared between them. Change both sides in one pull
request, and bump `format` when the shape changes.

## Inputs: `sources.toml`

```toml
[[repo]]
name = "runtime"                                # used in source ids and links
url = "https://github.com/ComlineProject/runtime"
default_branch = "main"
# A release tag: the named group `version` is the release's version.
tag = '^v(?P<version>\d+\.\d+\.\d+(?:[-+].*)?)$'

[[source]]
id = "runtime-bench"                            # [a-z0-9-]+, unique
kind = "bench"                                  # bench | fuzz | conformance | size | compile | coverage | ci
title = "Rust runtime"
repo = "runtime"
branch = "reports"
path = "rust.bench.json"

[[source]]
id = "wire-rust"
kind = "conformance"
matrix = "wire"                                 # conformance only: wire | codegen
title = "Rust runtime"
repo = "runtime"
branch = "main"
path = "runtime/conformance/reports/rust.json"
# conformance only: where the feature titles come from (the default branch's tip)
features = { repo = "runtime", path = "runtime/conformance/features.json" }
```

A source's **branch** is walked first-parent, oldest first; each commit that
changed `path` is one **version**.

## Versions

| Field | Meaning |
|---|---|
| `id` | the commit that published the version (on the source's branch), full hex |
| `commit` | the commit that was **measured**: the report's `commit` field when it has one, otherwise `id` |
| `date` | `id`'s committer date, ISO 8601 UTC (`2026-11-07T10:18:12Z`) |
| `cycle` | the release the version leads to: the version string of the **oldest** tag (by the tag commit's committer date) whose history contains `commit`; `"unreleased"` when no tag contains it, or when `commit` isn't in the repository |
| `label` | `<cycle>-dev.<n>`, or `unreleased-dev.<n>`; `n` counts from 1 within the cycle, in version order |
| `release` | on the **last** version of a released cycle only: that release's version string; otherwise `null` |
| `run` | the report's `run` URL, or `null` |
| `toolchain` | the report's `toolchain`, or `null` |

Versions are ordered by `date`, ties by walk order. A commit on the walk
that deleted `path` is not a version. If `commit` isn't in the repository it
stays as reported and the collector warns on stderr. A cycle's `date` is the
tag commit's committer date (not the tag object's). Labels are recomputed
from scratch on every run, so a new tag regroups older versions on its own.

## Output layout

```
<out>/
  manifest.json                       # never hashed; the only fixed name
  sources/<id>/index.<hash>.json
  sources/<id>/releases.<hash>.json
  sources/<id>/cycle-<cycle>.<hash>.json
  sources/<id>/v/<version id>.<hash>.json
```

`<hash>` is the first 12 hex digits of the SHA-256 of the file's bytes. All
JSON is written minified with sorted keys, so an unchanged input gives
byte-identical output and the same names. Paths inside files are relative to
`<out>`.

### `manifest.json`

```json
{
  "format": 1,
  "generated": "2026-11-08T12:00:00Z",
  "sources": [
    { "id": "runtime-bench", "kind": "bench", "title": "Rust runtime",
      "repo": "runtime", "matrix": null,
      "status": "ok", "index": "sources/runtime-bench/index.3f2a….json" },
    { "id": "wire-typescript", "kind": "conformance", "title": "TypeScript runtime",
      "repo": "comline-typescript", "matrix": "wire",
      "status": "unpublished", "reason": "path not found on branch main" }
  ]
}
```

A source that fails for any reason (unreachable, no versions, a report that
doesn't parse) is `"unpublished"` with a `reason`; the run still succeeds. The
collector exits non-zero only on a bad `sources.toml` or `--strict`.

### `index.<hash>.json`

```json
{
  "id": "runtime-bench", "kind": "bench", "title": "Rust runtime",
  "repo": "runtime", "repo_url": "https://github.com/ComlineProject/runtime",
  "branch": "reports", "path": "rust.bench.json", "matrix": null,
  "versions": [ { "id": "…", "commit": "…", "date": "…", "cycle": "unreleased",
                  "label": "unreleased-dev.1", "release": null,
                  "run": null, "toolchain": "rustc 1.98.0 (…)",
                  "shard": "sources/runtime-bench/v/<id>.<hash>.json" } ],
  "cycles": [ { "id": "0.1.0", "tag": "v0.1.0", "date": "…", "chunk": "sources/…/cycle-0.1.0.<hash>.json" },
              { "id": "unreleased", "tag": null, "date": null, "chunk": "…" } ],
  "releases": "sources/runtime-bench/releases.<hash>.json",
  "metrics": [ { "key": "comline2/answer", "metric": "instructions",
                 "unit": "instructions", "type": "number",
                 "group": "comline2", "param": null, "better": "lower" } ],
  "features": null
}
```

- `cycles` are in release order (tag date), `unreleased` last; only cycles
  with at least one version are listed.
- `metrics` is the union over all versions, sorted by `key` then `metric`. A
  chunk's `values[i]` belongs to `metrics[i]`.
- `group` is `key` up to its last `/` (`null` when there's none); `param` is the
  last segment when it is a plain integer, written as a JSON number
  (`ffi/abi/…/message/4096` → group `ffi/abi/…/message`, param `4096`), so
  payload-size families line up; `null` otherwise.
- `better` is `"higher"`, `"lower"` or `null`: which direction is an improvement
  (see "Which way is better"). `null` for `verdict` and `state` rows.
- `unit` is `null` for `verdict` and `state` rows. Fuzz units: `executions`,
  `inputs` (corpus), `findings`, `s` (seconds), `cases`. A format-2 bench
  metric's unit is its metric name.
- `features` (conformance only): `{ "<feature id>": { "title", "description" } }`
  from the source's `features` file; `null` otherwise.

### Chunks: `cycle-<cycle>.<hash>.json` and `releases.<hash>.json`

Columnar, aligned to a list of version indexes into `index.versions`:

```json
{ "versions": [0, 1, 2, 5],
  "values": [ [4718, 4718, null, 4720], … ] }
```

`values[i][j]` is `metrics[i]` at version `versions[j]`, or `null` when that
version doesn't have it. A cycle chunk holds that cycle's versions; the
releases chunk holds the one `release` version of each released cycle (empty
`versions` when there's no tag yet).

### Shards: `v/<version id>.<hash>.json`

The version's report, normalised per kind (below) and nothing else. Loaded
only when one version is opened or two are compared in detail.

## Kinds

### `bench`

Input (format 1, today's `rust.bench.json`):
`{ runtime, commit, toolchain, metric: "instructions", benches: { "<id>": { "ir": N } } }`.

- Metric rows: `key` = bench id, `metric` = `"instructions"`, `unit` =
  `"instructions"`, `type` = `"number"`.
- Input format 2 (see the proposal's "several metrics per benchmark"):
  `benches: { "<id>": { "<metric>": { "value", "runner"?, "spread"? } } }`. The
  collector accepts both. A format-2 metric becomes `metric` = `"<metric>"` when
  `runner` is absent or null, and `"<metric>@<runner>"` when it is present, so
  values from different runners are never in one series. `spread` is not carried
  yet.
- Shard: `{ "benches": { "<id>": { "<metric>": value } } }`.

### `fuzz`

Input: today's `rust.fuzz.json` (`runtime/fuzz/README.md#the-report` in the
runtime).

- Metric rows per target: `key` = target, `metric` ∈ `executions`, `corpus`,
  `findings`, `seconds`; `type` = `"number"`. A target with `error` has `null`
  for all four in that version (a gap, never a zero).
- A `proptest` verdict other than `pass` / `fail` is `null`.
- Metric rows per property: `key` = `proptest/<property>`, `metric` =
  `"verdict"`, `type` = `"verdict"`, values `"pass"` / `"fail"` / `null`.
- One row `key` = `proptest`, `metric` = `"cases"`, `type` = `"number"`.
- Shard: the input report unchanged except `commit`, `toolchain`, `date`,
  `run` (already in the version).

### `conformance`

Input, either shape:

- generation's `features.json`:
  `{ features: [{id,title,description}], generators: [{ name, support: { "<feature>": { state, proven_by, note, since, tracking, failing? } } }] }`;
- a runtime report: `{ runtime, support: { "<feature>": { state, proven_by, note?, tracking?, failing? } } }`.

- Metric rows: `key` = `<subject>/<feature>` (subject = the generator's `name`,
  or the value of the report's `runtime` field, e.g. `rust`), `metric` = `"state"`, `type` = `"state"`, values `"supported"` /
  `"partial"` / `"ignored"` / `"unsupported"` / `null` (also for any other
  value).
- generation's own `features` list (from the latest version) fills `index.features` there; a runtime
  report takes them from `features` in `sources.toml`.
- Shard: `{ "subjects": { "<subject>": { "<feature>": { state, proven_by, note, tracking, failing } } } }`
  with absent fields as `null` and `proven_by` / `failing` as sorted lists
  (`null` when absent). `since` is not carried.

**A matrix combines sources.** The site shows every source with the same
`matrix` as one table. Their histories are separate, so a matrix "version" is
a point in time: each source at its newest version on or before that date.
Labels can repeat across sources, so the site's URLs name a version as
`<source id>:<label>` (`?a=codegen:unreleased-dev.1`).

### `size`

Input (`<name>.size.json`):
`{ "format": 1, "commit", "toolchain", "run", "artifacts": { "<id>": { "bytes": N, "gzip_bytes": N? } } }`.
`<id>` names the artifact and how it was built, path-like
(`ffi/cdylib/x86_64-linux-release`, `ffi/wasm32-release`, `cli/x86_64-linux-release`).

- Metric rows: `key` = artifact id, `metric` ∈ `bytes`, `gzip_bytes`, `unit` =
  `"bytes"`, `type` = `"number"`. Lower is better.
- Shard: `{ "artifacts": { "<id>": { "bytes", "gzip_bytes" } } }`.

### `compile`

Input (`<name>.compile.json`):
`{ "format": 1, "commit", "toolchain", "run", "runner", "profile", "total_seconds": x, "units": { "<crate>": { "seconds": x } } }`
(a clean build of the workspace; the `report-rust-compile` action reads the unit
data embedded in `cargo build --timings`'s report, because cargo has no
`--timings=json` output, nightly included; `total_seconds` is the end of the
last unit, `units` sums a crate's units, build script included).

- Metric rows: `key` = crate, plus `key` = `total` for `total_seconds`;
  `metric` = `"seconds@<runner>"` (wall time is per runner, like bench format
  2), `unit` = `"s"`, `type` = `"number"`. Lower is better.
- Shard: the input without the envelope fields.

### `coverage`

Input (`<name>.coverage.json`):
`{ "format": 1, "commit", "toolchain", "run", "tool", "totals": C, "units": { "<unit>": C } }`
where `C` = `{ "lines": { "covered", "total" }, "functions": { … }?, "branches": { … }? }`
and a unit is a crate (Rust) or a top-level source directory (TypeScript).

- Metric rows: `key` = unit, plus `key` = `total` for `totals`; `metric` ∈
  `lines`, `functions`, `branches` (those present); value = covered ÷ total ×
  100, rounded to 2 decimals (`null` when total is 0); `unit` = `"%"`, `type` =
  `"number"`. **Higher is better.**
- Shard: `{ "totals": C, "units": { … } }` with the raw counts.

### `ci`

No producer and no report file: the collector reads workflow runs from the
GitHub REST API (`GET /repos/{owner}/{repo}/actions/runs`, token from
`GITHUB_TOKEN` or `GH_TOKEN` when set). A source is
`{ id, kind = "ci", title, repo }`.

- **Versions** are completed runs on the repo's `default_branch` whose event is
  `push`, `schedule` or `workflow_dispatch`, newest 1000 at most. `id` =
  `run-<run id>`, `commit` = the run's `head_sha`, `date` = `run_started_at`
  (else `created_at`), `run` = its `html_url`; cycles and labels as for every
  version.
- Metric rows: `key` = workflow name; `metric` ∈ `duration_s` (`updated_at` −
  `run_started_at`; `unit` `"s"`), `attempts` (`run_attempt`; a value above 1
  is a rerun), `conclusion` (`type` `"verdict"`: `success` → `"pass"`,
  `failure` / `timed_out` → `"fail"`, anything else → `null`). A version only
  has values for its own workflow; the rest are `null`.
- `attempts` has `unit` `null` and `better` `"lower"`; `duration_s` has `unit`
  `"s"`, `better` `"lower"`; `conclusion` has `better` `null`.
- A ci version belongs to exactly one workflow: the one whose rows are non-null
  in it (the rest are `null`).
- A "last N days" window over ci versions counts back from the **newest run's**
  `date`, not from the current time, so a quiet repo still shows its history.
- Sizes are decimal: 1 KB = 1000 bytes, 1 MB = 1000 KB (sites format `bytes` that way).
- Shard: `{ "workflow", "event", "conclusion", "run_attempt", "duration_s", "html_url" }`.
- Without a token the API allows 60 requests an hour, which is enough for a
  local run of a few sources; CI passes the job's token.

### Which way is better

The site needs to know whether a rise is good or bad: `coverage`, and fuzz
`executions` and `corpus`, are higher-is-better; every other number is
lower-is-better. The collector writes the answer into each metric row as
`better`; `verdict` and `state` rows have `null`. (A ci `attempts` count is
lower-is-better like the rest.)

## Running

```
python3 collector/collect.py --sources sources.toml --out site/static/data \
    [--cache .cache/repos] [--local runtime=/path/to/runtime ...] [--strict] [--no-network]
```

- `--cache` keeps blobless clones between runs (`git clone --filter=blob:none
  --no-checkout`, then `git fetch --tags` and each needed branch).
- `--local name=path` reads an existing checkout instead of cloning. It uses
  that checkout's `origin/<branch>` refs and tags, and never writes to it.
- `--no-network` skips the GitHub API: `ci` sources are unpublished ("ci needs
  the network"). Repositories are still cloned or fetched in the cache.
- A `ci` source's `branch` in the index is the repo's `default_branch` and its
  `path` is `null`; the repo clone (cache or `--local`) is used for tags and
  ancestry only, so a repo without a matching tag has every run `unreleased`.
  An API failure (rate limit, network) unpublishes that source with the reason.
- Exit status: `0` on success, `2` on a bad `sources.toml` (or bad
  arguments), `1` with `--strict` when any source is unpublished. If a
  `--local` or cache repository can't be read the sources using it are
  unpublished.
- `generated` in the manifest is the current time, or `SOURCE_DATE_EPOCH`
  when that is set (the only non-deterministic byte in the output).
- `--out/sources/` is deleted at the start of every run, so stale hashed files
  don't pile up; nothing else outside it is removed.
- `--strict` exits non-zero when any source is unpublished (for local checks;
  CI doesn't pass it).
- Python 3.11+ standard library only (`tomllib`), plus `git`.

`collector/synthetic.py --scale N --out <dir>` writes a dataset in the same
format, N times today's size (versions and metrics), for the site's
performance budget test.
