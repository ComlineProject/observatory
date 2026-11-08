<script lang="ts">
	import { onMount } from 'svelte';
	import { UrlState } from '$lib/url.svelte';
	import VersionPicker from '$lib/VersionPicker.svelte';
	import VirtualTable from '$lib/VirtualTable.svelte';
	import { pickItems } from '$lib/pick';
	import { fmtNum, loadManifest, loadSource, type ManifestSource, type Source } from '$lib/data.svelte';

	const REFERENCE = 'runtime-bench';
	const url = new UrlState(['ref', 'other']);

	let benches = $state<ManifestSource[] | null>(null);
	let err = $state('');
	let loaded = $state<Record<string, Source>>({});
	let group = $state('');
	let text = $state('');
	let sortBy = $state<'ratio' | 'key'>('ratio');
	let desc = $state(true);
	let showOnly = $state(false);

	onMount(() => {
		loadManifest().then(
			(m) => (benches = m.sources.filter((s) => s.kind === 'bench' && s.status === 'ok')),
			(e) => (err = String(e.message ?? e))
		);
	});

	/** `?ref=<source>:<label>`: the label is optional (the newest version). */
	function parse(v: string | null): [string, string | null] | null {
		if (!v) return null;
		const i = v.indexOf(':');
		return i < 0 ? [v, null] : [v.slice(0, i), v.slice(i + 1) || null];
	}
	let ids = $derived(benches?.map((b) => b.id) ?? []);
	let refId = $derived.by(() => {
		const p = parse(url.get('ref'));
		return p && ids.includes(p[0]) ? p[0] : ids.includes(REFERENCE) ? REFERENCE : (ids[0] ?? '');
	});
	let otherId = $derived.by(() => {
		const p = parse(url.get('other'));
		return p && ids.includes(p[0]) ? p[0] : (ids.find((i) => i !== refId) ?? '');
	});
	let enough = $derived(benches !== null && benches.length >= 2);

	// Load whatever the URL names.
	$effect(() => {
		for (const id of [refId, otherId]) {
			if (!id || !enough || loaded[id]) continue;
			loadSource(id).then(
				async (s) => {
					await s.loadInitial();
					loaded[id] = s;
				},
				(e) => (err = String(e.message ?? e))
			);
		}
	});

	let refSrc = $derived(loaded[refId]);
	let otherSrc = $derived(loaded[otherId]);
	function versionOf(s: Source | undefined, param: string | null): number | null {
		if (!s) return null;
		const l = parse(param)?.[1];
		return (l ? s.byLabel.get(l) : undefined) ?? s.latest();
	}
	let refV = $derived(versionOf(refSrc, url.get('ref')));
	let otherV = $derived(versionOf(otherSrc, url.get('other')));

	$effect(() => {
		if (refSrc && refV !== null) refSrc.loadVersion(refV);
		if (otherSrc && otherV !== null) otherSrc.loadVersion(otherV);
	});

	async function pickSource(side: 'ref' | 'other', id: string) {
		const s = await loadSource(id);
		await s.loadInitial();
		loaded[id] = s;
		url.set({ [side]: `${id}:${s.index.versions.at(-1)!.label}` });
	}
	function pickVersion(side: 'ref' | 'other', label: string) {
		url.set({ [side]: `${side === 'ref' ? refId : otherId}:${label}` });
	}

	interface Row {
		key: string;
		metric: string;
		name: string;
		group: string | null;
		family: string;
		r: number;
		o: number;
		ratio: number;
	}
	const family = (key: string) => key.split('/')[0];
	const idOf = (key: string, metric: string) => `${key}\0${metric}`;

	let ready = $derived(
		(void refSrc?.rev, void otherSrc?.rev, !!refSrc && !!otherSrc && refV !== null && otherV !== null && refSrc.hasVersion(refV) && otherSrc.hasVersion(otherV))
	);

	/** Every key both sides have a number for, plus the ones only one side has. */
	let joined = $derived.by(() => {
		const rows: Row[] = [];
		const onlyRef: string[] = [];
		const onlyOther: string[] = [];
		if (!ready || !refSrc || !otherSrc || refV === null || otherV === null) return { rows, onlyRef, onlyOther };
		void refSrc.rev, otherSrc.rev;
		const theirs = new Map<string, number>();
		otherSrc.index.metrics.forEach((m, i) => {
			const v = otherSrc!.columns[i][otherV!];
			if (typeof v === 'number') theirs.set(idOf(m.key, m.metric), v);
		});
		refSrc.index.metrics.forEach((m, i) => {
			const r = refSrc!.columns[i][refV!];
			if (typeof r !== 'number') return;
			const id = idOf(m.key, m.metric);
			const o = theirs.get(id);
			const name = m.metric === 'instructions' ? m.key : `${m.key} · ${m.metric}`;
			if (o === undefined) onlyRef.push(name);
			else if (r > 0) {
				rows.push({ key: m.key, metric: m.metric, name, group: m.group, family: family(m.key), r, o, ratio: o / r });
			}
		});
		const have = new Set(refSrc.index.metrics.map((m) => idOf(m.key, m.metric)));
		for (const m of otherSrc.index.metrics) {
			if (typeof theirs.get(idOf(m.key, m.metric)) === 'number' && !have.has(idOf(m.key, m.metric)))
				onlyOther.push(m.metric === 'instructions' ? m.key : `${m.key} · ${m.metric}`);
		}
		return { rows, onlyRef, onlyOther };
	});

	function geomean(rs: Row[]) {
		let sum = 0,
			n = 0;
		for (const x of rs) if (x.ratio > 0) ((sum += Math.log(x.ratio)), n++);
		return n ? Math.exp(sum / n) : null;
	}
	let summary = $derived.by(() => {
		const fams = new Map<string, Row[]>();
		for (const r of joined.rows) (fams.get(r.family) ?? fams.set(r.family, []).get(r.family)!).push(r);
		return {
			all: geomean(joined.rows),
			families: [...fams].map(([name, rs]) => ({ name, n: rs.length, g: geomean(rs) })).sort((a, b) => a.name.localeCompare(b.name))
		};
	});
	let groups = $derived([...new Set(joined.rows.map((r) => r.group).filter((g): g is string => !!g))].sort());

	let rows = $derived.by(() => {
		const t = text.toLowerCase();
		const out = joined.rows.filter(
			(r) => (!group || r.group === group || (r.group ?? '').startsWith(group + '/')) && (!t || r.name.toLowerCase().includes(t))
		);
		const s = desc ? -1 : 1;
		out.sort((x, y) => (sortBy === 'key' ? s * x.name.localeCompare(y.name) : s * (x.ratio - y.ratio) || x.name.localeCompare(y.name)));
		return out;
	});

	function sort(by: 'ratio' | 'key') {
		if (sortBy === by) desc = !desc;
		else ((sortBy = by), (desc = by === 'ratio'));
	}
	const arrow = (by: string) => (sortBy === by ? (desc ? ' ▾' : ' ▴') : '');
	const fmtRatio = (x: number | null) => (x === null ? '–' : `${x.toFixed(2)}×`);
	const titleOf = (id: string) => benches?.find((b) => b.id === id)?.title ?? id;
</script>

<svelte:head><title>Benchmarks: ratio to Rust · Comline Observatory</title></svelte:head>

<h1>Benchmarks: ratio to Rust</h1>
{#if err}<p class="error">{err}</p>{/if}

{#if benches === null}
	{#if !err}<p class="muted">loading…</p>{/if}
{:else if !enough}
	<p class="secondary" data-testid="ratio-unpublished">
		The second runtime hasn't published benchmarks yet, so there is nothing to compare. This page needs two published bench sources;
		{benches.length} {benches.length === 1 ? 'is' : 'are'} published.
	</p>
{:else}
	<p class="secondary">
		How many times more instructions another runtime spends than the reference, on the same workload (ratio = other ÷ reference).
	</p>
	<p class="muted note" data-testid="ratio-note">
		Both are instruction counts under callgrind. For a JIT runtime they are counted after warm-up, so compare orders of magnitude and
		trends rather than single-digit percentages.
	</p>

	<div class="row">
		<span>Reference</span>
		<select value={refId} aria-label="reference source" onchange={(e) => pickSource('ref', e.currentTarget.value)}>
			{#each benches as b (b.id)}<option value={b.id} disabled={b.id === otherId}>{b.title}</option>{/each}
		</select>
		{#if refSrc && refV !== null}
			<VersionPicker name="ref" items={pickItems(refSrc)} value={refSrc.index.versions[refV].label} onpick={(l) => pickVersion('ref', l)} />
		{/if}
		<span>Other</span>
		<select value={otherId} aria-label="other source" onchange={(e) => pickSource('other', e.currentTarget.value)}>
			{#each benches as b (b.id)}<option value={b.id} disabled={b.id === refId}>{b.title}</option>{/each}
		</select>
		{#if otherSrc && otherV !== null}
			<VersionPicker name="other" items={pickItems(otherSrc)} value={otherSrc.index.versions[otherV].label} onpick={(l) => pickVersion('other', l)} />
		{/if}
	</div>

	{#if !ready}
		<p class="muted">loading…</p>
	{:else}
		<div class="summary" data-testid="ratio-summary">
			<div class="stat">
				<div class="big" data-testid="ratio-geomean">{fmtRatio(summary.all)}</div>
				<div class="muted small">geometric mean, {fmtNum(joined.rows.length)} keys</div>
			</div>
			{#each summary.families as f (f.name)}
				<div class="stat">
					<div class="mid">{fmtRatio(f.g)}</div>
					<div class="muted small">{f.name} · {fmtNum(f.n)}</div>
				</div>
			{/each}
		</div>

		<div class="row">
			<label>group
				<select bind:value={group}>
					<option value="">all</option>
					{#each groups as g (g)}<option value={g}>{g}</option>{/each}
				</select>
			</label>
			<label>filter <input type="text" bind:value={text} placeholder="name contains…" /></label>
		</div>

		<div data-testid="ratio-table">
			<VirtualTable {rows} height={480} empty="No keys in common at these versions.">
				{#snippet header()}
					<tr>
						<th><button type="button" class="link" onclick={() => sort('key')}>key{arrow('key')}</button></th>
						<th class="num">{titleOf(refId)}</th>
						<th class="num">{titleOf(otherId)}</th>
						<th class="num"><button type="button" class="link" onclick={() => sort('ratio')}>ratio{arrow('ratio')}</button></th>
					</tr>
				{/snippet}
				{#snippet row(r: Row)}
					<tr>
						<td title={r.name}>{r.name}</td>
						<td class="num">{fmtNum(r.r)}</td>
						<td class="num">{fmtNum(r.o)}</td>
						<td class="num">{fmtRatio(r.ratio)}</td>
					</tr>
				{/snippet}
			</VirtualTable>
		</div>

		<p class="muted small" data-testid="ratio-only">
			{fmtNum(joined.onlyRef.length)} keys only in {titleOf(refId)}, {fmtNum(joined.onlyOther.length)} only in {titleOf(otherId)}.
			{#if joined.onlyRef.length + joined.onlyOther.length}
				<button type="button" class="link" onclick={() => (showOnly = !showOnly)}>{showOnly ? 'hide' : 'show'}</button>
			{/if}
		</p>
		{#if showOnly}
			<div class="only">
				{#each [[refId, joined.onlyRef], [otherId, joined.onlyOther]] as [id, list] (id)}
					{#if list.length}
						<details open>
							<summary>only in {titleOf(id as string)} ({list.length})</summary>
							<ul class="mono">
								{#each list as k (k)}<li>{k}</li>{/each}
							</ul>
						</details>
					{/if}
				{/each}
			</div>
		{/if}
	{/if}
{/if}

<style>
	.note {
		font-size: 13px;
		max-width: 80ch;
	}
	.summary {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		margin: 12px 0;
	}
	.stat {
		padding: 8px 12px;
		background: var(--surface-1);
		border: 1px solid var(--border);
		border-radius: 8px;
		min-width: 110px;
	}
	.big {
		font-size: 26px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}
	.mid {
		font-size: 18px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.small {
		font-size: 12px;
	}
	.link {
		border: 0;
		background: transparent;
		padding: 0;
		font: inherit;
		font-weight: 600;
		color: inherit;
		cursor: pointer;
	}
	.only ul {
		max-height: 240px;
		overflow: auto;
		font-size: 12px;
		margin: 4px 0 8px;
	}
</style>
