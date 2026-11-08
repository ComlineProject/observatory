<script lang="ts">
	// One card per source: status, latest version, a sparkline over the newest cycle.
	// Everything comes from the one summary file, never from a source's own data.
	import { base } from '$app/paths';
	import Sparkline from './Sparkline.svelte';
	import { onMount } from 'svelte';
	import { loadSummary, shortDate, type CardSummary, type ManifestSource } from './data.svelte';

	let { sources, ratio = false }: { sources: ManifestSource[]; ratio?: boolean } = $props();

	function href(m: ManifestSource) {
		if (m.kind === 'conformance') return `${base}/conformance/${m.matrix}/`;
		return `${base}/${m.kind}/${m.id}/`;
	}

	let summary = $state<Record<string, CardSummary>>({});
	let err = $state('');
	onMount(() => {
		loadSummary().then(
			(x) => (summary = x),
			(e) => (err = String(e))
		);
	});
</script>


{#if err}<p class="error">{err}</p>{/if}
<div class="cards">
	{#each sources as m (m.id)}
		{@const c = summary[m.id]}
		<a class="card" href={href(m)} data-source={m.id}>
			<div class="kind muted">{m.kind}{m.matrix ? ` · ${m.matrix}` : ''}</div>
			<div class="title">{m.title}</div>
			{#if m.status !== 'ok'}
				<div class="muted">Not published yet: {m.reason}</div>
			{:else if c}
				<div class="secondary">
					{c.label} · {shortDate(c.date)}
					{#if c.release}<span class="muted">(release {c.release})</span>{/if}
				</div>
				<Sparkline values={c.spark} label="{c.sparkLabel}, newest cycle" />
				<div class="muted small">{c.sparkLabel}, newest cycle</div>
				{#if c.badge}<div class="state small">{#if c.badge.cls}<span class="swatch {c.badge.cls}"></span>{/if}{c.badge.text}</div>{/if}
			{:else if !err}
				<div class="muted">loading…</div>
			{/if}
		</a>
	{/each}
	{#if ratio}
		<a class="card" href="{base}/ratio/" data-source="ratio">
			<div class="kind muted">bench · cross-runtime</div>
			<div class="title">Benchmarks: ratio to Rust</div>
			<div class="secondary">Instruction counts of another runtime over the Rust reference, per shared workload.</div>
		</a>
	{/if}
</div>

<style>
	.cards {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: 12px;
		margin-top: 8px;
	}
	.card {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 12px 14px;
		background: var(--surface-1);
		border: 1px solid var(--border);
		border-radius: 8px;
		color: inherit;
		text-decoration: none;
		min-height: 150px;
	}
	.card:hover {
		border-color: var(--text-muted);
	}
	.kind {
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.title {
		font-weight: 600;
		font-size: 16px;
	}
	.small {
		font-size: 12px;
	}
</style>
