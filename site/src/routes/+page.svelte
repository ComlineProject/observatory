<script lang="ts">
	import { base } from '$app/paths';
	import { onMount } from 'svelte';
	import Sparkline from '$lib/Sparkline.svelte';
	import { loadManifest, loadSource, shortDate, type ManifestSource, type Source } from '$lib/data.svelte';

	interface Card {
		m: ManifestSource;
		src?: Source;
		err?: string;
		spark?: (number | null)[];
		sparkLabel?: string;
		badge?: { text: string; cls: string };
	}
	let cards = $state<Card[]>([]);
	let err = $state('');
	let twoBenches = $derived(cards.filter((c) => c.m.kind === 'bench' && c.m.status === 'ok').length >= 2);

	function href(m: ManifestSource) {
		if (m.kind === 'conformance') return `${base}/conformance/${m.matrix}/`;
		return `${base}/${m.kind}/${m.id}/`;
	}

	/** Per-version summary over the newest cycle (already loaded with the page). */
	function summarise(c: Card, s: Source) {
		const [lo, hi] = s.cycleRange(s.index.cycles.length - 1);
		const ms = s.index.metrics;
		const idx = Array.from({ length: hi - lo + 1 }, (_, k) => lo + k);
		if (s.index.kind === 'bench') {
			// geometric mean of each metric relative to its value at the newest version
			c.sparkLabel = "geometric mean, relative to the newest version";
			c.spark = idx.map((v) => {
				let sum = 0,
					n = 0;
				ms.forEach((_, i) => {
					const b = s.columns[i][hi],
						x = s.columns[i][v];
					if (typeof b === 'number' && typeof x === 'number' && b > 0 && x > 0) ((sum += Math.log(x / b)), n++);
				});
				return n ? Math.exp(sum / n) : null;
			});
		} else if (s.index.kind === 'fuzz') {
			c.sparkLabel = 'total executions';
			c.spark = idx.map((v) => {
				let t = 0,
					any = false;
				ms.forEach((m, i) => {
					const x = s.columns[i][v];
					if (m.metric === 'executions' && typeof x === 'number') ((t += x), (any = true));
				});
				return any ? t : null;
			});
			const last = s.latest();
			let findings = 0,
				fails = 0;
			ms.forEach((m, i) => {
				const x = s.columns[i][last];
				if (m.metric === 'findings' && typeof x === 'number') findings += x;
				if (m.type === 'verdict' && x === 'fail') fails++;
			});
			c.badge =
				findings || fails
					? { text: `${findings} findings, ${fails} failing properties`, cls: 's-fail' }
					: { text: 'no findings, all properties pass', cls: 's-pass' };
		} else {
			c.sparkLabel = 'supported cells';
			c.spark = idx.map((v) => ms.reduce((n, _, i) => n + (s.columns[i][v] === 'supported' ? 1 : 0), 0));
			const last = s.latest();
			const counts: Record<string, number> = {};
			ms.forEach((_, i) => {
				const x = s.columns[i][last];
				if (typeof x === 'string') counts[x] = (counts[x] ?? 0) + 1;
			});
			c.badge = {
				text: ['supported', 'partial', 'ignored', 'unsupported']
					.filter((k) => counts[k])
					.map((k) => `${counts[k]} ${k}`)
					.join(', '),
				cls: counts.unsupported ? 's-partial' : 's-supported'
			};
		}
	}

	onMount(async () => {
		try {
			const m = await loadManifest();
			cards = m.sources.map((s) => ({ m: s }));
			await Promise.all(
				cards.map(async (c, k) => {
					if (c.m.status !== 'ok') return;
					try {
						const s = await loadSource(c.m.id);
						await s.loadCycle(s.index.cycles.length - 1);
						const card = cards[k];
						card.src = s;
						summarise(card, s);
					} catch (e) {
						cards[k].err = String(e);
					}
				})
			);
		} catch (e) {
			err = String(e);
		}
	});
</script>

<svelte:head><title>Comline Observatory</title></svelte:head>

<h1>Comline Observatory</h1>
<p class="secondary">Benchmarks, fuzzing and conformance over every published version.</p>
{#if err}<p class="error">{err}</p>{/if}

<div class="cards">
	{#each cards as c (c.m.id)}
		{@const latest = c.src?.index.versions.at(-1)}
		<a class="card" href={href(c.m)} data-source={c.m.id}>
			<div class="kind muted">{c.m.kind}{c.m.matrix ? ` · ${c.m.matrix}` : ''}</div>
			<div class="title">{c.m.title}</div>
			{#if c.m.status !== 'ok'}
				<div class="muted">Not published yet: {c.m.reason}</div>
			{:else if c.err}
				<div class="error">{c.err}</div>
			{:else if latest}
				<div class="secondary">
					{latest.label} · {shortDate(latest.date)}
					{#if latest.release}<span class="muted">(release {latest.release})</span>{/if}
				</div>
				{#if c.spark}<Sparkline values={c.spark} label="{c.sparkLabel}, newest cycle" />
					<div class="muted small">{c.sparkLabel}, newest cycle</div>{/if}
				{#if c.badge}<div class="state small"><span class="swatch {c.badge.cls}"></span>{c.badge.text}</div>{/if}
			{:else}
				<div class="muted">loading…</div>
			{/if}
		</a>
	{/each}
	{#if twoBenches}
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
		margin-top: 16px;
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
