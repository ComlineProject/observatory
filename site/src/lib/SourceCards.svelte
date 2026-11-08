<script lang="ts">
	// One card per source: status, latest version, a sparkline over the newest cycle.
	import { base } from '$app/paths';
	import Sparkline from './Sparkline.svelte';
	import { loadSource, shortDate, fmtUnit, type ManifestSource, type Source } from './data.svelte';

	let { sources, ratio = false }: { sources: ManifestSource[]; ratio?: boolean } = $props();

	interface Card {
		m: ManifestSource;
		src?: Source;
		err?: string;
		spark?: (number | null)[];
		sparkLabel?: string;
		badge?: { text: string; cls: string };
	}
	let cards = $state<Card[]>([]);

	function href(m: ManifestSource) {
		if (m.kind === 'conformance') return `${base}/conformance/${m.matrix}/`;
		return `${base}/${m.kind}/${m.id}/`;
	}

	/** Sum of the rows matching `pick` at each version (null when none has a value). */
	function sumAt(s: Source, idx: number[], pick: (i: number) => boolean) {
		return idx.map((v) => {
			let t = 0,
				any = false;
			s.index.metrics.forEach((_, i) => {
				const x = s.columns[i][v];
				if (pick(i) && typeof x === 'number') ((t += x), (any = true));
			});
			return any ? t : null;
		});
	}

	/** Per-version summary over the newest cycle (already loaded with the page). */
	function summarise(c: Card, s: Source) {
		const [lo, hi] = s.cycleRange(s.index.cycles.length - 1);
		const ms = s.index.metrics;
		const idx = Array.from({ length: hi - lo + 1 }, (_, k) => lo + k);
		const last = s.latest();
		const row = (key: string, metric: string) => ms.findIndex((m) => m.key === key && m.metric === metric);
		switch (s.index.kind) {
			case 'bench':
				// geometric mean of each metric relative to its value at the newest version
				c.sparkLabel = 'geometric mean, relative to the newest version';
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
				break;
			case 'fuzz': {
				c.sparkLabel = 'total executions';
				c.spark = sumAt(s, idx, (i) => ms[i].metric === 'executions');
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
				break;
			}
			case 'size': {
				c.sparkLabel = 'total bytes, all artifacts';
				c.spark = sumAt(s, idx, (i) => ms[i].metric === 'bytes');
				const t = sumAt(s, [last], (i) => ms[i].metric === 'bytes')[0];
				c.badge = { text: `${fmtUnit(t, 'bytes')} in ${new Set(ms.map((m) => m.key)).size} artifacts`, cls: '' };
				break;
			}
			case 'compile': {
				const r = ms.findIndex((m) => m.key === 'total');
				c.sparkLabel = 'total build time';
				c.spark = idx.map((v) => (r >= 0 ? (s.columns[r][v] as number | null) : null));
				if (r >= 0) c.badge = { text: `${fmtUnit(s.columns[r][last], 's')} clean build`, cls: '' };
				break;
			}
			case 'coverage': {
				const r = row('total', 'lines');
				c.sparkLabel = 'total line coverage';
				c.spark = idx.map((v) => (r >= 0 ? (s.columns[r][v] as number | null) : null));
				if (r >= 0) c.badge = { text: `${fmtUnit(s.columns[r][last], '%')} of lines covered`, cls: '' };
				break;
			}
			case 'ci': {
				const verdicts = ms.flatMap((m, i) => (m.metric === 'conclusion' ? [i] : []));
				const at = (v: number) => verdicts.map((i) => s.columns[i][v]).find((x) => x === 'pass' || x === 'fail');
				const seq = idx.map(at);
				const W = 10;
				c.sparkLabel = `pass rate, last ${W} runs`;
				c.spark = seq.map((_, k) => {
					const w = seq.slice(Math.max(0, k - W + 1), k + 1).filter((x) => x);
					return w.length ? (w.filter((x) => x === 'pass').length / w.length) * 100 : null;
				});
				const judged = seq.filter((x) => x);
				const pass = judged.filter((x) => x === 'pass').length;
				const rate = judged.length ? (pass / judged.length) * 100 : null;
				c.badge = {
					text: `${rate === null ? '–' : rate.toFixed(0) + '%'} of ${judged.length} runs passed`,
					cls: rate !== null && rate < 90 ? 's-fail' : 's-pass'
				};
				break;
			}
			default: {
				c.sparkLabel = 'supported cells';
				c.spark = idx.map((v) => ms.reduce((n, _, i) => n + (s.columns[i][v] === 'supported' ? 1 : 0), 0));
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
	}

	$effect(() => {
		cards = sources.map((s) => ({ m: s }));
	});

	// A card loads its source's index and newest cycle only once it scrolls near
	// the viewport: with many sources the overview would otherwise fetch them all.
	async function load(k: number) {
		const m = cards[k]?.m;
		if (!m || m.status !== 'ok') return;
		try {
			const s = await loadSource(m.id);
			await s.loadCycle(s.index.cycles.length - 1);
			if (cards[k]?.m !== m) return;
			const card = cards[k];
			card.src = s;
			summarise(card, s);
		} catch (e) {
			if (cards[k]?.m === m) cards[k].err = String(e);
		}
	}
	function visible(node: HTMLElement, k: number) {
		const io = new IntersectionObserver(
			(es) => {
				if (es.some((e) => e.isIntersecting)) {
					io.disconnect();
					load(k);
				}
			},
			{ rootMargin: '200px' }
		);
		io.observe(node);
		return { destroy: () => io.disconnect() };
	}
</script>

<div class="cards">
	{#each cards as c, k (c.m.id)}
		{@const latest = c.src?.index.versions.at(-1)}
		<a class="card" href={href(c.m)} data-source={c.m.id} use:visible={k}>
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
				{#if c.badge}<div class="state small">{#if c.badge.cls}<span class="swatch {c.badge.cls}"></span>{/if}{c.badge.text}</div>{/if}
			{:else}
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
