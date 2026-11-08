<script lang="ts">
	import Chart, { type SeriesSpec } from './Chart.svelte';
	import VirtualTable from './VirtualTable.svelte';
	import VersionPicker from './VersionPicker.svelte';
	import { fmtNum, metricName, type Source } from './data.svelte';
	import { MAX_SERIES, SERIES, pickItems } from './pick';
	import type { Ctx } from './SourcePage.svelte';

	import { untrack } from 'svelte';

	let { src, ctx }: { src: Source; ctx: Ctx } = $props();
	// The source is fixed for this component's lifetime (its parent is keyed by id).
	const S = untrack(() => src);
	const versions = S.index.versions;
	const metrics = S.index.metrics;
	const xs = versions.map((_, i) => i);
	const xLabel = (x: number) => versions[Math.round(x)]?.label ?? '';

	// Series → colour slot; a series keeps its colour while it stays selected.
	let slots = $state<Record<number, number>>({});
	let selected = $derived(
		Object.entries(slots)
			.map(([i, s]) => [Number(i), s] as const)
			.sort((x, y) => x[1] - y[1])
	);
	function toggle(i: number) {
		if (i in slots) delete slots[i];
		else {
			const used = new Set(Object.values(slots));
			const free = SERIES.findIndex((_, k) => !used.has(k));
			if (free >= 0) slots[i] = free;
		}
	}

	let filtered = $derived.by(() => {
		const t = ctx.text.toLowerCase();
		const g = ctx.group;
		const out: number[] = [];
		metrics.forEach((m, i) => {
			if (g && m.group !== g && !(m.group ?? '').startsWith(g + '/')) return;
			if (t && !metricName(m).toLowerCase().includes(t)) return;
			out.push(i);
		});
		return out;
	});
	// Start with the first few series.
	untrack(() => filtered.slice(0, 3).forEach((i) => toggle(i)));

	// The visible range starts on the newest cycle (loaded with the page).
	function cycleRange(ci: number): [number, number] {
		const [lo, hi] = src.cycleRange(ci);
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

	let ys = $derived((void src.rev, selected.map(([i]) => src.columns[i].slice() as (number | null)[])));
	let series = $derived<SeriesSpec[]>(selected.map(([i, s]) => ({ label: metricName(metrics[i]), color: SERIES[s] })));
	let marks = $derived([
		...src.releaseIdx.map((i) => ({ x: i, label: versions[i].release! })),
		...ctx.marked.filter((i) => !versions[i].release).map((i) => ({ x: i, label: versions[i].label }))
	]);
	let at = $derived(ctx.at ?? versions.length - 1);

	// Payload-size view: families whose rows have a numeric param.
	const families = (() => {
		const f = new Map<string, number[]>();
		metrics.forEach((m, i) => {
			if (m.param !== null && m.group) f.set(m.group, [...(f.get(m.group) ?? []), i]);
		});
		for (const v of f.values()) v.sort((x, y) => metrics[x].param! - metrics[y].param!);
		return f;
	})();
	let familyNames = $derived([...families.keys()].filter((g) => !ctx.group || g === ctx.group || g.startsWith(ctx.group + '/')));
	let family = $state('');
	let fam = $derived(familyNames.includes(family) ? family : (familyNames[0] ?? ''));
	let payloadAt = $state<string | null>(null);
	let pv = $derived(payloadAt !== null ? (src.byLabel.get(payloadAt) ?? at) : at);
	$effect(() => {
		src.loadVersion(pv);
		for (const v of ctx.marked) src.loadVersion(v);
	});
	let pVersions = $derived(ctx.marked.length ? ctx.marked.slice(0, MAX_SERIES) : [pv]);
	let pRows = $derived(families.get(fam) ?? []);
	let pxs = $derived(pRows.map((i) => metrics[i].param!));
	let pys = $derived((void src.rev, pVersions.map((v) => pRows.map((i) => src.columns[i][v] as number | null))));
	let pseries = $derived(pVersions.map((v, k) => ({ label: versions[v].label, color: SERIES[k] })));
	const items = pickItems(S);
</script>

<div class="row">
	<label>range
		<select value={rangeSel} onchange={(e) => setRange(e.currentTarget.value)}>
			{#each src.index.cycles as c, ci (c.id)}
				<option value={String(ci)}>{c.id === 'unreleased' ? 'unreleased (since the last release)' : `cycle → ${c.id}`}</option>
			{/each}
			<option value="all">all history</option>
			{#if rangeSel === 'zoom'}<option value="zoom">zoomed</option>{/if}
		</select>
	</label>
	<span class="muted">Drag on the chart to zoom, double-click to reset; click a point to open that version.</span>
</div>

<div class="panel">
	{#if selected.length === 0}<p class="muted">Select series in the table below.</p>{/if}
	<Chart {xs} {ys} {series} {xLabel} {marks} xRange={range} {onrange} yLabel="instructions" onpick={(x) => ctx.open(x)} />
</div>

<VirtualTable rows={filtered} height={300}>
	{#snippet header()}
		<tr><th style="width: 2em"></th><th>series ({selected.length}/{MAX_SERIES} on the chart)</th><th class="num">at {versions[at].label}</th></tr>
	{/snippet}
	{#snippet row(i: number)}
		<tr>
			<td>
				<input
					type="checkbox"
					aria-label="show {metricName(metrics[i])}"
					checked={i in slots}
					disabled={!(i in slots) && selected.length >= MAX_SERIES}
					onchange={() => toggle(i)}
				/>
			</td>
			<td title={metricName(metrics[i])}>
				{#if i in slots}<span class="swatch" style:background="var({SERIES[slots[i]]})"></span>{/if}
				{metricName(metrics[i])}
			</td>
			<td class="num">{(void src.rev, fmtNum(src.columns[i][at]))}</td>
		</tr>
	{/snippet}
</VirtualTable>

{#if familyNames.length}
	<h2>Payload size</h2>
	<div class="row">
		<label>family
			<select value={fam} onchange={(e) => (family = e.currentTarget.value)}>
				{#each familyNames as f (f)}<option value={f}>{f}</option>{/each}
			</select>
		</label>
		{#if ctx.marked.length}
			<span class="muted">showing the {pVersions.length} chosen versions</span>
		{:else}
			<span>at</span>
			<VersionPicker name="payload" {items} value={versions[pv].label} onpick={(k) => (payloadAt = k)} />
		{/if}
	</div>
	<div class="panel">
		<Chart xs={pxs} ys={pys} series={pseries} xLabel={(x) => `${x} B`} logX yLabel="instructions" height={260} />
	</div>
{/if}
