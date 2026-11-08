<script lang="ts">
	// CI (DATA.md `ci`): one version per workflow run. Per workflow: pass rate,
	// a verdict strip with reruns ringed, and duration over time.
	import { onMount } from 'svelte';
	import Chart, { type SeriesSpec } from './Chart.svelte';
	import VerdictStrip from './VerdictStrip.svelte';
	import { fmtAxis, fmtUnit, loadSource, shortCommit, shortDate, type Source } from './data.svelte';
	import { SERIES } from './pick';
	import { UrlState } from './url.svelte';

	let { id }: { id: string } = $props();
	const url = new UrlState(['range']);
	let src = $state<Source | null>(null);
	let err = $state('');
	onMount(() => {
		loadSource(id).then(
			async (s) => {
				await s.loadInitial();
				src = s;
			},
			(e) => (err = String(e.message ?? e))
		);
	});

	const RANGES = [
		['30', 'last 30 days'],
		['90', 'last 90 days'],
		['all', 'all runs']
	] as const;
	let range = $derived(url.get('range') ?? '30');

	/** [lo, hi] version indexes in the range, counted back from the newest run. */
	let span = $derived.by<[number, number]>(() => {
		if (!src) return [0, 0];
		const vs = src.index.versions;
		const hi = vs.length - 1;
		if (range === 'all' || hi < 0) return [0, hi];
		const from = Date.parse(vs[hi].date) - Number(range) * 86400e3;
		let lo = hi;
		while (lo > 0 && Date.parse(vs[lo - 1].date) >= from) lo--;
		return [lo, hi];
	});
	$effect(() => {
		if (src) src.loadRange(span[0], span[1]);
	});

	interface Wf {
		name: string;
		conclusion: number;
		duration: number;
		attempts: number;
	}
	let workflows = $derived.by<Wf[]>(() => {
		if (!src) return [];
		const by = new Map<string, Wf>();
		src.index.metrics.forEach((m, i) => {
			const w = by.get(m.key) ?? { name: m.key, conclusion: -1, duration: -1, attempts: -1 };
			if (m.metric === 'conclusion') w.conclusion = i;
			else if (m.metric === 'duration_s') w.duration = i;
			else if (m.metric === 'attempts') w.attempts = i;
			by.set(m.key, w);
		});
		return [...by.values()].sort((a, b) => a.name.localeCompare(b.name));
	});

	interface Row {
		w: Wf;
		runs: number[];
		pass: number;
		fail: number;
		reruns: number;
		medianS: number | null;
	}
	let rows = $derived.by<Row[]>(() => {
		if (!src) return [];
		void src.rev;
		const s = src;
		return workflows.map((w) => {
			const runs: number[] = [];
			let pass = 0,
				fail = 0,
				reruns = 0;
			const ds: number[] = [];
			for (let v = span[0]; v <= span[1]; v++) {
				const c = w.conclusion >= 0 ? s.columns[w.conclusion][v] : undefined;
				const d = w.duration >= 0 ? s.columns[w.duration][v] : undefined;
				const a = w.attempts >= 0 ? s.columns[w.attempts][v] : undefined;
				// A version belongs to this workflow when any of its rows has a value.
				if (c == null && d == null && a == null) continue;
				runs.push(v);
				if (c === 'pass') pass++;
				else if (c === 'fail') fail++;
				if (typeof a === 'number' && a > 1) reruns++;
				if (typeof d === 'number') ds.push(d);
			}
			ds.sort((x, y) => x - y);
			return { w, runs, pass, fail, reruns, medianS: ds.length ? ds[Math.floor(ds.length / 2)] : null };
		});
	});
	let loading = $derived((void src?.rev, !!src && !(src.hasVersion(span[0]) && src.hasVersion(span[1]))));

	function rate(r: Row) {
		const n = r.pass + r.fail;
		return n ? (r.pass / n) * 100 : null;
	}

	// Duration chart: x = run index, one series per workflow (first 8), joined across other workflows' runs.
	let shown = $derived(rows.slice(0, SERIES.length));
	let xs = $derived(src ? Array.from({ length: src.index.versions.length }, (_, i) => i) : []);
	let ys = $derived((void src?.rev, src ? shown.map((r) => (r.w.duration >= 0 ? (src!.columns[r.w.duration].slice() as (number | null)[]) : xs.map(() => null))) : []));
	let series = $derived<SeriesSpec[]>(shown.map((r, k) => ({ label: r.w.name, color: SERIES[k] })));
	const xLabel = (x: number) => shortDate(src?.index.versions[Math.round(x)]?.date ?? null);
	let marks = $derived(src ? src.releaseIdx.map((i) => ({ x: i, label: src!.index.versions[i].release! })) : []);

	function openRun(vi: number) {
		const r = src?.index.versions[vi]?.run;
		if (r) window.open(r, '_blank', 'noopener');
	}
	function cells(r: Row) {
		const s = src!;
		return r.runs.map((v) => {
			const ver = s.index.versions[v];
			const a = r.w.attempts >= 0 ? s.columns[r.w.attempts][v] : null;
			const d = r.w.duration >= 0 ? s.columns[r.w.duration][v] : null;
			return {
				v: r.w.conclusion >= 0 ? s.columns[r.w.conclusion][v] : null,
				vi: v,
				label: `${shortDate(ver.date)} ${shortCommit(ver.commit)}, ${fmtUnit(d, 's')}${typeof a === 'number' && a > 1 ? `, attempt ${a}` : ''}`,
				ring: typeof a === 'number' && a > 1
			};
		});
	}
</script>

<svelte:head><title>CI{src ? `: ${src.index.title}` : ''} · Comline Observatory</title></svelte:head>

<h1>CI{src ? `: ${src.index.title}` : ''}</h1>
{#if src}
	<p class="secondary">
		<a href={src.index.repo_url}>{src.index.repo}</a> · workflow runs on the default branch · {src.index.versions.length} runs, {workflows.length} workflows
	</p>
{/if}
{#if err}<p class="error">{err}</p>{/if}

<div class="row">
	<label>range
		<select value={range} onchange={(e) => url.set({ range: e.currentTarget.value === '30' ? null : e.currentTarget.value })}>
			{#each RANGES as [k, l] (k)}<option value={k}>{l}</option>{/each}
		</select>
	</label>
	{#if src && src.index.versions.length}
		<span class="muted">counted back from the newest run ({shortDate(src.index.versions.at(-1)!.date)}){loading ? ' · loading…' : ''}</span>
	{/if}
</div>

{#if !src}
	{#if !err}<p class="muted">loading…</p>{/if}
{:else}
	<table class="wf panel" data-testid="ci-workflows">
		<thead>
			<tr><th>workflow</th><th class="num">runs</th><th class="num">pass rate</th><th class="num">failed</th><th class="num">reruns</th><th class="num">median duration</th></tr>
		</thead>
		<tbody>
			{#each rows as r (r.w.name)}
				{@const p = rate(r)}
				<tr>
					<td>{r.w.name}</td>
					<td class="num">{r.runs.length}</td>
					<td class="num">{p === null ? '–' : `${p.toFixed(1)}%`}</td>
					<td class="num">{r.fail}</td>
					<td class="num">{r.reruns}</td>
					<td class="num">{fmtUnit(r.medianS, 's')}</td>
				</tr>
			{/each}
		</tbody>
	</table>
	<p class="muted small">Pass rate counts runs that passed or failed; cancelled and skipped runs have no verdict and are left out.</p>

	<h2>Runs</h2>
	<p class="muted small">
		<span class="state"><span class="swatch s-pass"></span>pass</span>
		<span class="state"><span class="swatch s-fail"></span>fail</span>
		<span class="state"><span class="swatch s-none"></span>no verdict</span>
		<span class="state"><span class="swatch ring"></span>rerun (attempt &gt; 1)</span>
		· oldest left; click a run to open it on GitHub
	</p>
	<VerdictStrip rows={rows.map((r) => ({ name: r.w.name, cells: cells(r) }))} onpick={openRun} ringLabel="rerun" />

	<h2>Duration</h2>
	<div class="panel">
		<Chart
			{xs}
			{ys}
			{series}
			{xLabel}
			{marks}
			xRange={[span[0], Math.max(span[1], span[0] + 1)]}
			yLabel="seconds"
			fmtY={(v) => fmtAxis(v, 's')}
			fmtV={(v) => fmtUnit(v, 's')}
			spanGaps
			onpick={openRun}
		/>
	</div>
	{#if rows.length > shown.length}<p class="muted small">The first {shown.length} workflows are drawn.</p>{/if}
{/if}

<style>
	.wf {
		width: 100%;
		border-collapse: collapse;
	}
	.wf th,
	.wf td {
		padding: 4px 8px;
		text-align: left;
	}
	.wf .num {
		text-align: right;
	}
	.swatch.ring {
		outline: 2px solid var(--text-primary);
		outline-offset: -2px;
	}
	.small {
		font-size: 12px;
	}
</style>
