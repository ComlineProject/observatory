<script lang="ts">
	import Chart, { type SeriesSpec } from './Chart.svelte';
	import VirtualTable from './VirtualTable.svelte';
	import VersionPicker from './VersionPicker.svelte';
	import { fmtAxis, fmtUnit, unitLabel, type Source } from './data.svelte';
	import { MAX_SERIES, SERIES, pickItems } from './pick';
	import type { Ctx } from './SourcePage.svelte';
	import { UrlState } from './url.svelte';

	import { untrack } from 'svelte';

	let { src, ctx }: { src: Source; ctx: Ctx } = $props();
	// The source is fixed for this component's lifetime (its parent is keyed by id).
	const S = untrack(() => src);
	const versions = S.index.versions;
	const metrics = S.index.metrics;
	const xs = versions.map((_, i) => i);
	const xLabel = (x: number) => versions[Math.round(x)]?.label ?? '';

	// Chart state in the URL (shareable; back/forward work): `?s=` the series
	// (keys, or `.<index>` when the keys would make a long URL), `?x=` the
	// visible range as `<from label>..<to label>`.
	const url = new UrlState(['s', 'x']);
	const keyOf = (i: number) => (S.multiMetric ? `${metrics[i].key}~${metrics[i].metric}` : metrics[i].key);
	const byKey = new Map(metrics.map((_, i) => [keyOf(i), i]));
	function decodeS(v: string | null): number[] {
		if (v === null) return metrics.slice(0, 3).map((_, i) => i);
		if (v === '~') return [];
		const out: number[] = [];
		for (const k of v.split(',')) {
			const i = /^\.\d+$/.test(k) ? Number(k.slice(1)) : byKey.get(k);
			if (i !== undefined && i < metrics.length && !out.includes(i)) out.push(i);
		}
		return out.slice(0, MAX_SERIES);
	}
	function encodeS(is: number[]): string {
		if (!is.length) return '~';
		const keys = is.map(keyOf).join(',');
		return keys.length <= 240 ? keys : is.map((i) => `.${i}`).join(',');
	}

	// Series → colour slot; a series keeps its colour while it stays selected.
	let slots: Record<number, number> = {};
	let wanted = $derived(decodeS(url.get('s')));
	let selected = $derived.by(() => {
		const keep: Record<number, number> = {};
		for (const i of wanted) if (i in slots) keep[i] = slots[i];
		const used = new Set(Object.values(keep));
		for (const i of wanted)
			if (!(i in keep)) {
				const free = SERIES.findIndex((_, k) => !used.has(k));
				if (free < 0) break;
				keep[i] = free;
				used.add(free);
			}
		slots = keep;
		return wanted.filter((i) => i in keep).map((i) => [i, keep[i]] as const);
	});
	let slotOf = $derived(Object.fromEntries(selected) as Record<number, number>);
	function toggle(i: number) {
		const cur = selected.map(([j]) => j);
		const next = cur.includes(i) ? cur.filter((j) => j !== i) : [...cur, i];
		url.set({ s: encodeS(next) });
	}

	let filtered = $derived.by(() => {
		const t = ctx.text.toLowerCase();
		const g = ctx.group;
		const out: number[] = [];
		metrics.forEach((m, i) => {
			if (g && m.group !== g && !(m.group ?? '').startsWith(g + '/')) return;
			if (t && !S.nameOf(m).toLowerCase().includes(t)) return;
			out.push(i);
		});
		return out;
	});

	// The visible range starts on the newest cycle (loaded with the page).
	function cycleRange(ci: number): [number, number] {
		const [lo, hi] = src.cycleRange(ci);
		return hi > lo ? [lo, hi] : [Math.max(0, lo - 1), Math.max(hi, 1)];
	}
	const newest = S.index.cycles.length - 1;
	const clampR = (lo: number, hi: number): [number, number] => [Math.max(0, lo), Math.min(versions.length - 1, Math.max(hi, lo + 1))];
	let range = $derived.by<[number, number]>(() => {
		const x = url.get('x');
		const m = x?.match(/^(.+)\.\.(.+)$/);
		const lo = m ? src.byLabel.get(m[1]) : undefined;
		const hi = m ? src.byLabel.get(m[2]) : undefined;
		return lo !== undefined && hi !== undefined && hi > lo ? clampR(lo, hi) : cycleRange(newest);
	});
	let rangeSel = $derived.by(() => {
		const [lo, hi] = range;
		if (lo === 0 && hi === Math.max(1, versions.length - 1) && url.get('x') !== null) return 'all';
		for (let ci = 0; ci < S.index.cycles.length; ci++) {
			const [a, b] = cycleRange(ci);
			if (a === lo && b === hi) return String(ci);
		}
		return 'zoom';
	});
	$effect(() => {
		src.loadRange(range[0], range[1]);
	});
	function setX(lo: number, hi: number) {
		const [a, b] = cycleRange(newest);
		url.set({ x: lo === a && hi === b ? null : `${versions[lo].label}..${versions[hi].label}` });
	}
	function setRange(v: string) {
		if (v === 'all') setX(0, Math.max(1, versions.length - 1));
		else if (v !== 'zoom') setX(...cycleRange(Number(v)));
	}
	function onrange(lo: number, hi: number) {
		const r = clampR(lo, hi);
		if (r[0] === range[0] && r[1] === range[1]) return;
		setX(r[0], r[1]);
	}

	let ys = $derived((void src.rev, selected.map(([i]) => src.columns[i].slice() as (number | null)[])));
	let series = $derived<SeriesSpec[]>(selected.map(([i, s]) => ({ label: S.nameOf(metrics[i]), color: SERIES[s] })));
	let marks = $derived([
		...src.releaseIdx.map((i) => ({ x: i, label: versions[i].release! })),
		...ctx.marked.filter((i) => !versions[i].release).map((i) => ({ x: i, label: versions[i].label }))
	]);
	let at = $derived(ctx.at ?? versions.length - 1);
	// The axis unit: the first selected series' (a source's numbers share one unit per kind).
	let unit = $derived(selected.length ? metrics[selected[0][0]].unit : (metrics[0]?.unit ?? null));
	let fmtY = $derived((v: number) => fmtAxis(v, unit));
	let fmtV = $derived((v: number) => fmtUnit(v, unit));

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
	<Chart {xs} {ys} {series} {xLabel} {marks} xRange={range} {onrange} yLabel={unitLabel(unit)} {fmtY} {fmtV} onpick={(x) => ctx.open(x)} />
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
					aria-label="show {S.nameOf(metrics[i])}"
					checked={i in slotOf}
					disabled={!(i in slotOf) && selected.length >= MAX_SERIES}
					onchange={() => toggle(i)}
				/>
			</td>
			<td title={S.nameOf(metrics[i])}>
				{#if i in slotOf}<span class="swatch" style:background="var({SERIES[slotOf[i]]})"></span>{/if}
				{S.nameOf(metrics[i])}
			</td>
			<td class="num">{(void src.rev, fmtUnit(src.columns[i][at], metrics[i].unit))}</td>
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
		<Chart xs={pxs} ys={pys} series={pseries} xLabel={(x) => `${x} B`} logX logY yLabel={unitLabel(unit)} {fmtY} {fmtV} height={260} />
	</div>
{/if}
