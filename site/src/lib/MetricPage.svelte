<script lang="ts">
	// Size, compile and coverage: the bench page's machinery, with the unit and
	// regression direction taken from each metric (DATA.md).
	import SourcePage from './SourcePage.svelte';
	import BenchChart from './BenchChart.svelte';
	import Shard from './Shard.svelte';
	import VirtualTable from './VirtualTable.svelte';
	import { fmtUnit, kindLabel, type Kind } from './data.svelte';

	let { id, kind }: { id: string; kind: Kind } = $props();

	type Counts = { covered: number; total: number } | undefined;
	type Cov = { lines?: Counts; functions?: Counts; branches?: Counts };
	type Report = {
		artifacts?: Record<string, { bytes?: number | null; gzip_bytes?: number | null }>;
		units?: Record<string, { seconds?: number } | Cov>;
		totals?: Cov;
		total_seconds?: number;
		runner?: string;
		profile?: string;
		tool?: string;
	};
	const cnt = (c: Counts) => (c ? `${c.covered.toLocaleString('en-US')} / ${c.total.toLocaleString('en-US')}` : '–');

	function table(s: Report): { cols: string[]; rows: string[][]; note: string } {
		if (kind === 'size')
			return {
				cols: ['artifact', 'bytes', 'gzip'],
				rows: Object.entries(s.artifacts ?? {}).map(([k, a]) => [k, fmtUnit(a.bytes, 'bytes'), fmtUnit(a.gzip_bytes, 'bytes')]),
				note: ''
			};
		if (kind === 'compile')
			return {
				cols: ['crate', 'seconds'],
				rows: [
					['total', fmtUnit(s.total_seconds ?? null, 's')],
					...Object.entries(s.units ?? {}).map(([k, u]) => [k, fmtUnit((u as { seconds?: number }).seconds ?? null, 's')])
				],
				note: [s.runner && `runner ${s.runner}`, s.profile && `profile ${s.profile}`].filter(Boolean).join(' · ')
			};
		const units: [string, Cov][] = [['total', s.totals ?? {}], ...(Object.entries(s.units ?? {}) as [string, Cov][])];
		return {
			cols: ['unit', 'lines', 'functions', 'branches'],
			rows: units.map(([k, c]) => [k, cnt(c.lines), cnt(c.functions), cnt(c.branches)]),
			note: s.tool ? `tool ${s.tool}` : ''
		};
	}
</script>

<SourcePage {id} heading={kindLabel(kind)}>
	{#snippet chart(src, ctx)}
		<BenchChart {src} {ctx} />
	{/snippet}
	{#snippet detail(src, vi)}
		<Shard {src} {vi}>
			{#snippet children(s: Report)}
				{@const t = table(s)}
				{#if t.note}<p class="muted">{t.note}</p>{/if}
				<VirtualTable rows={t.rows} height={360}>
					{#snippet header()}
						<tr>{#each t.cols as c, k (c)}<th class:num={k > 0}>{c}</th>{/each}</tr>
					{/snippet}
					{#snippet row(r: string[])}
						<tr>{#each r as c, k (k)}<td class:num={k > 0} title={k === 0 ? c : undefined}>{c}</td>{/each}</tr>
					{/snippet}
				</VirtualTable>
			{/snippet}
		</Shard>
	{/snippet}
</SourcePage>
