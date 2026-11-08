<script lang="ts" module>
	export interface Ctx {
		/** The opened version (`?at=`), or null. */
		at: number | null;
		open: (vi: number) => void;
		/** Versions chosen in the N-versions view, drawn as marks on the chart. */
		marked: number[];
		group: string;
		text: string;
	}
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';
	import { onMount } from 'svelte';
	import { UrlState } from './url.svelte';
	import { loadSource, shortCommit, shortDate, type Metric, type Source } from './data.svelte';
	import VersionPicker from './VersionPicker.svelte';
	import DeltaTable from './DeltaTable.svelte';
	import MultiGrid from './MultiGrid.svelte';
	import { pickItems } from './pick';

	let {
		id,
		heading,
		chart,
		detail,
		direction
	}: {
		id: string;
		heading: string;
		chart: Snippet<[Source, Ctx]>;
		detail: Snippet<[Source, number]>;
		direction?: (m: Metric) => number;
	} = $props();

	const url = new UrlState(['a', 'b', 'v', 'at']);
	let src = $state<Source | null>(null);
	let err = $state('');
	let group = $state('');
	let text = $state('');
	let threshold = $state(0);

	onMount(() => {
		loadSource(id).then(
			async (s) => {
				await s.loadInitial();
				src = s;
			},
			(e) => (err = String(e.message ?? e))
		);
	});

	const idx = (l: string | null) => (l && src ? (src.byLabel.get(l) ?? null) : null);
	let a = $derived(idx(url.get('a')));
	let b = $derived(idx(url.get('b')));
	let at = $derived(idx(url.get('at')));
	let vs = $derived(
		(url.get('v') ?? '')
			.split(',')
			.map((l) => idx(l))
			.filter((x): x is number => x !== null)
	);
	let mode = $derived(url.get('a') !== null || url.get('b') !== null ? 'compare' : url.get('v') !== null ? 'multi' : 'chart');

	// Anything referenced from the URL gets its chunk (and the opened one its shard).
	$effect(() => {
		if (!src) return;
		for (const v of [a, b, at, ...vs]) if (v !== null) src.loadVersion(v);
	});

	let items = $derived(src ? pickItems(src) : []);
	let groups = $derived.by(() => {
		if (!src) return [];
		const g = new Set<string>();
		for (const m of src.index.metrics) if (m.group) g.add(m.group);
		return [...g].sort();
	});

	function label(v: number) {
		return src!.index.versions[v].label;
	}
	function setMode(m: string) {
		if (!src) return;
		const last = src.latest();
		if (m === 'chart') url.set({ a: null, b: null, v: null });
		else if (m === 'compare') {
			const rel = src.releaseIdx.filter((r) => r < last);
			const aa = a ?? (rel.length ? rel.at(-1)! : Math.max(0, last - 1));
			url.set({ a: label(aa), b: label(b ?? last), v: null });
		} else {
			const pick = vs.length ? vs : src.releaseIdx.length ? [...src.releaseIdx, last] : [Math.max(0, last - 4), last];
			url.set({ a: null, b: null, v: [...new Set(pick)].map(label).join(',') });
		}
	}
	function allReleases() {
		if (!src) return;
		const r = src.releaseIdx.length ? src.releaseIdx : [src.latest()];
		url.set({ v: r.map(label).join(',') });
	}
	function addVersion(l: string) {
		const cur = (url.get('v') ?? '').split(',').filter(Boolean);
		if (!cur.includes(l)) cur.push(l);
		cur.sort((x, y) => (idx(x) ?? 0) - (idx(y) ?? 0));
		url.set({ v: cur.join(',') });
	}
	function removeVersion(l: string) {
		url.set({ v: (url.get('v') ?? '').split(',').filter((x) => x && x !== l).join(',') || null });
	}

	let ctx = $derived<Ctx>({ at, open: (vi) => url.set({ at: label(vi) }), marked: mode === 'multi' ? vs : [], group, text });
</script>

<svelte:head><title>{heading}{src ? `: ${src.index.title}` : ''} · Comline Observatory</title></svelte:head>

<h1>{heading}{src ? `: ${src.index.title}` : ''}</h1>
{#if src}
	<p class="secondary">
		<a href={src.index.repo_url}>{src.index.repo}</a> · <span class="mono">{src.index.branch}:{src.index.path}</span> ·
		{src.index.versions.length} versions, {src.index.metrics.length} series
	</p>
{/if}
{#if err}<p class="error">{err}</p>{/if}

<div class="row" role="tablist">
	<button role="tab" class:on={mode === 'chart'} aria-selected={mode === 'chart'} onclick={() => setMode('chart')}>History</button>
	<button role="tab" class:on={mode === 'compare'} aria-selected={mode === 'compare'} onclick={() => setMode('compare')} data-testid="tab-compare"
		>Compare A / B</button
	>
	<button role="tab" class:on={mode === 'multi'} aria-selected={mode === 'multi'} onclick={() => setMode('multi')}>N versions</button>
</div>

<div class="row">
	<label>group
		<select bind:value={group}>
			<option value="">all</option>
			{#each groups as g (g)}<option value={g}>{g}</option>{/each}
		</select>
	</label>
	<label>filter <input type="text" bind:value={text} placeholder="name contains…" /></label>
	{#if mode === 'compare'}
		<label>|Δ%| ≥ <input type="number" min="0" step="0.5" bind:value={threshold} style="width: 5em" /></label>
	{/if}
</div>

{#if !src}
	{#if !err}<p class="muted">loading…</p>{/if}
{:else if mode === 'compare'}
	<div class="row">
		<span>A</span>
		<VersionPicker name="a" {items} value={url.get('a')} onpick={(k) => url.set({ a: k })} />
		<span>B</span>
		<VersionPicker name="b" {items} value={url.get('b')} onpick={(k) => url.set({ b: k })} />
	</div>
	{#if a !== null && b !== null}
		<DeltaTable {src} {a} {b} {group} {threshold} {text} {direction} />
	{:else}
		<p class="muted">Pick two versions.</p>
	{/if}
{:else}
	{#if mode === 'multi'}
		<div class="row">
			<button onclick={allReleases}>all releases</button>
			<span>add</span>
			<VersionPicker name="add" {items} value={null} onpick={addVersion} />
			{#each vs as v (v)}
				<span class="chip">{label(v)} <button aria-label="remove {label(v)}" onclick={() => removeVersion(label(v))}>×</button></span>
			{/each}
		</div>
	{/if}
	{@render chart(src, ctx)}
	{#if mode === 'multi'}
		<h2>Values at {vs.length} versions</h2>
		<MultiGrid {src} {vs} {group} {text} />
	{/if}
{/if}

{#if src && at !== null}
	{@const v = src.index.versions[at]}
	<section class="panel" data-testid="version-detail">
		<div class="row" style="justify-content: space-between">
			<h2 style="margin: 0">Version {v.label}{v.release ? ` (release ${v.release})` : ''}</h2>
			<button onclick={() => url.set({ at: null })}>close</button>
		</div>
		<p class="secondary">
			{shortDate(v.date)} · measured <a class="mono" href="{src.index.repo_url}/commit/{v.commit}">{shortCommit(v.commit)}</a>
			{#if v.id !== v.commit}· published <a class="mono" href="{src.index.repo_url}/commit/{v.id}">{shortCommit(v.id)}</a>{/if}
			{#if v.run}· <a href={v.run}>run</a>{/if}
			{#if v.toolchain}· <span class="mono">{v.toolchain}</span>{/if}
		</p>
		{@render detail(src, at)}
	</section>
{/if}

<style>
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 0 0 0 8px;
		border: 1px solid var(--border);
		border-radius: 12px;
		font-size: 12px;
	}
	.chip button {
		border: 0;
		padding: 0 6px;
		background: transparent;
	}
</style>
