<script lang="ts">
	import { untrack } from 'svelte';
	import Chart, { type SeriesSpec } from './Chart.svelte';
	import VerdictStrip from './VerdictStrip.svelte';
	import { fmtNum, type Source } from './data.svelte';
	import { MAX_SERIES, SERIES } from './pick';
	import type { Ctx } from './SourcePage.svelte';

	let { src, ctx }: { src: Source; ctx: Ctx } = $props();
	const S = untrack(() => src);
	const versions = S.index.versions;
	const metrics = S.index.metrics;
	const xs = versions.map((_, i) => i);
	const xLabel = (x: number) => versions[Math.round(x)]?.label ?? '';

	const targets = [...new Set(metrics.filter((m) => m.type === 'number' && m.key !== 'proptest').map((m) => m.key))].sort();
	const kinds = ['executions', 'corpus', 'findings', 'seconds'].filter((k) => metrics.some((m) => m.metric === k));
	const properties = metrics.map((m, i) => [m, i] as const).filter(([m]) => m.type === 'verdict');
	const rowOf = new Map(metrics.map((m, i) => [`${m.key}\u0000${m.metric}`, i]));

	let kind = $state(kinds[0] ?? 'executions');
	let slots = $state<Record<string, number>>({});
	function toggle(t: string) {
		if (t in slots) delete slots[t];
		else {
			const used = new Set(Object.values(slots));
			const free = SERIES.findIndex((_, k) => !used.has(k));
			if (free >= 0) slots[t] = free;
		}
	}
	targets.slice(0, 4).forEach(toggle);
	let shownTargets = $derived(targets.filter((t) => !ctx.text || t.toLowerCase().includes(ctx.text.toLowerCase())));
	let selected = $derived(Object.entries(slots).sort((x, y) => x[1] - y[1]));

	function cycleRange(ci: number): [number, number] {
		const [lo, hi] = S.cycleRange(ci);
		return hi > lo ? [lo, hi] : [Math.max(0, lo - 1), Math.max(hi, 1)];
	}
	let range = $state<[number, number]>(cycleRange(S.index.cycles.length - 1));
	let rangeSel = $state(String(S.index.cycles.length - 1));
	function setRange(v: string) {
		rangeSel = v;
		if (v === 'all') {
			range = [0, Math.max(1, versions.length - 1)];
			src.loadAll();
		} else {
			range = cycleRange(Number(v));
			src.loadCycle(Number(v));
		}
	}
	function onrange(lo: number, hi: number) {
		if (lo === range[0] && hi === range[1]) return;
		range = [Math.max(0, lo), Math.min(versions.length - 1, hi)];
		rangeSel = 'zoom';
		src.loadRange(range[0], range[1]);
	}

	// Nulls stay null: a night that didn't run is a gap, never a zero.
	let ys = $derived(
		(void src.rev,
		selected.map(([t]) => {
			const i = rowOf.get(`${t}\u0000${kind}`);
			return i === undefined ? xs.map(() => null) : (src.columns[i].slice() as (number | null)[]);
		}))
	);
	let series = $derived<SeriesSpec[]>(selected.map(([t, s]) => ({ label: t, color: SERIES[s] })));
	let marks = $derived([
		...src.releaseIdx.map((i) => ({ x: i, label: versions[i].release! })),
		...ctx.marked.filter((i) => !versions[i].release).map((i) => ({ x: i, label: versions[i].label }))
	]);
	let strip = $derived.by(() => {
		void src.rev;
		const lo = Math.max(0, Math.floor(range[0])),
			hi = Math.min(versions.length - 1, Math.ceil(range[1]));
		const vs = Array.from({ length: hi - lo + 1 }, (_, k) => lo + k);
		return { vs, rows: properties.map(([m, i]) => ({ name: m.key.replace(/^proptest\//, ''), vals: vs.map((v) => src.columns[i][v]) })) };
	});
	const unit = (k: string) => metrics.find((m) => m.metric === k)?.unit ?? k;
</script>

<div class="row">
	<label>measure
		<select bind:value={kind}>
			{#each kinds as k (k)}<option value={k}>{k}</option>{/each}
		</select>
	</label>
	<label>range
		<select value={rangeSel} onchange={(e) => setRange(e.currentTarget.value)}>
			{#each src.index.cycles as c, ci (c.id)}
				<option value={String(ci)}>{c.id === 'unreleased' ? 'unreleased (since the last release)' : `cycle → ${c.id}`}</option>
			{/each}
			<option value="all">all history</option>
			{#if rangeSel === 'zoom'}<option value="zoom">zoomed</option>{/if}
		</select>
	</label>
	<span class="muted">Gaps are runs where the target didn't run. Click a point to open that version.</span>
</div>

<div class="panel">
	<Chart {xs} {ys} {series} {xLabel} {marks} xRange={range} {onrange} yLabel={unit(kind)} onpick={(x) => ctx.open(x)} />
</div>

<details open={targets.length <= 12}>
	<summary>targets ({selected.length}/{MAX_SERIES} on the chart, {targets.length} in all)</summary>
	<div class="targets">
		{#each shownTargets as t (t)}
			<label>
				<input type="checkbox" checked={t in slots} disabled={!(t in slots) && selected.length >= MAX_SERIES} onchange={() => toggle(t)} />
				{#if t in slots}<span class="swatch" style:background="var({SERIES[slots[t]]})"></span>{/if}
				{t}
			</label>
		{/each}
	</div>
</details>

{#if properties.length}
	<h2>Property tests</h2>
	<p class="muted small">
		<span class="state"><span class="swatch s-pass"></span>pass</span>
		<span class="state"><span class="swatch s-fail"></span>fail</span>
		<span class="state"><span class="swatch s-none"></span>no verdict</span>
		· {strip.vs.length} versions in the chart's range
	</p>
	<VerdictStrip
		rows={strip.rows.map((r) => ({ name: r.name, cells: r.vals.map((v, k) => ({ v, vi: strip.vs[k], label: versions[strip.vs[k]].label })) }))}
		onpick={(vi) => ctx.open(vi)}
	/>
{/if}
{#if ctx.at !== null}
	<p class="muted small">cases at {versions[ctx.at].label}: {fmtNum(src.columns[rowOf.get('proptest\u0000cases') ?? -1]?.[ctx.at])}</p>
{/if}

<style>
	.targets {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
		gap: 2px 12px;
		padding: 6px 0;
		max-height: 220px;
		overflow: auto;
	}
	.targets label {
		display: flex;
		gap: 6px;
		align-items: center;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.small {
		font-size: 12px;
	}
</style>
