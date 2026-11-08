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
