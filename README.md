# Observatory

Comline's benchmark, fuzzing and conformance results over time, published at
<https://comlineproject.github.io/observatory/>. Every published version can be
opened, and any two (or more) compared.

Design: [the project dashboard proposal](https://comlineproject.github.io/docs/proposals/project-dashboard/).

- **Producers** are the other repositories' CI. Each commits a JSON report to
  its own `reports` branch (or to `main`, for the committed conformance
  matrices). Every commit that changes a report is one version.
  They publish with this repository's action:

  ```yaml
  - uses: ComlineProject/observatory/.github/actions/publish-report@v1
    with:
      reports: typescript.bench.json
  ```

  (`permissions: contents: write`, a checkout with `fetch-depth: 0`, and never
  from a pull request: see [`action.yml`](.github/actions/publish-report/action.yml).)
- Reports that are measured the same way everywhere have actions too, each
  writing a report file for `publish-report` (inputs are in each `action.yml`):

  ```yaml
  - uses: ComlineProject/observatory/.github/actions/report-size@v1
    with:
      output: reports/rust.size.json
      toolchain: ${{ steps.rust.outputs.cachekey }}   # optional
      artifacts: |
        ffi/cdylib/x86_64-linux-release=target/release/libcomline_ffi.so
        ffi/wasm32-release=target/wasm32-unknown-unknown/release/*.wasm
  - uses: ComlineProject/observatory/.github/actions/report-rust-coverage@v1
    with:
      output: reports/rust.coverage.json
      args: --workspace            # extra cargo-llvm-cov arguments
  - uses: ComlineProject/observatory/.github/actions/report-rust-compile@v1
    with:
      output: reports/rust.compile.json
      args: --workspace --release  # cargo build arguments (a clean build)
      runner: github-hosted        # the machine class; times compare per runner
  # Fuzzing: each fuzz job records its target, then one job combines them.
  - uses: ComlineProject/observatory/.github/actions/report-fuzz@v1
    with:
      mode: target
      name: ids_parse
      log: ${{ runner.temp }}/fuzz.log   # libFuzzer's output, -print_final_stats=1
      corpus: core/fuzz/corpus/ids_parse
      artifacts: core/fuzz/artifacts/ids_parse
      toolchain: rustc …
      fragment: ${{ runner.temp }}/stats/ids_parse.json
  - uses: ComlineProject/observatory/.github/actions/report-fuzz@v1
    with:
      mode: combine
      fragments: ${{ runner.temp }}/stats   # the downloaded fragments
      expect: ids_parse ids_compile idp_parse
      output: reports/core.fuzz.json
  ```

  The coverage and compile actions expect the Rust toolchain to be set up
  already. The `ci` sources need no producer: the collector reads the GitHub API.
- **`collector/`** (Python standard library) walks those histories and writes
  the dataset described in [`DATA.md`](DATA.md). What it reads is listed in
  [`sources.toml`](sources.toml).
- **`site/`** (SvelteKit, static) renders the dataset.

The site is rebuilt and deployed daily, a few times a day for new benchmark
runs, and on demand. Gates stay in each repository's own CI: this site only
shows results.

## Running locally

```sh
python3 collector/collect.py --sources sources.toml --out site/static/data \
    --local runtime=../runtime --local generation=../generation
cd site && npm ci && npm run dev
```
