<script lang="ts">
	import { page } from '$app/state';
	import SourcePage from '$lib/SourcePage.svelte';
	import FuzzChart from '$lib/FuzzChart.svelte';
	import Shard from '$lib/Shard.svelte';
	import VirtualTable from '$lib/VirtualTable.svelte';
	import { fmtNum, type Metric } from '$lib/data.svelte';

	interface Target {
		seconds?: number | null;
		executions?: number | null;
		corpus?: number | null;
		findings?: number | null;
		error?: string;
	}
	interface FuzzShard {
		targets?: Record<string, Target>;
		proptest?: { cases?: number; properties?: Record<string, string>; error?: string } | null;
	}
	let id = $derived(page.params.source ?? '');
	// executions and corpus: more is better; findings and verdicts: more is worse.
	const direction = (m: Metric) => (m.metric === 'executions' || m.metric === 'corpus' ? -1 : m.metric === 'findings' ? 1 : 0);
</script>

{#key id}
	<SourcePage {id} heading="Fuzzing" {direction}>
		{#snippet chart(src, ctx)}
			<FuzzChart {src} {ctx} />
		{/snippet}
		{#snippet detail(src, vi)}
			<Shard {src} {vi}>
				{#snippet children(s: FuzzShard)}
					<VirtualTable rows={Object.entries(s.targets ?? {})} height={300}>
						{#snippet header()}
							<tr><th>target</th><th class="num">executions</th><th class="num">corpus</th><th class="num">findings</th><th class="num">seconds</th><th>error</th></tr>
						{/snippet}
						{#snippet row([name, t]: [string, Target])}
							<tr>
								<td>{name}</td>
								<td class="num">{fmtNum(t.executions)}</td>
								<td class="num">{fmtNum(t.corpus)}</td>
								<td class="num">{fmtNum(t.findings)}</td>
								<td class="num">{fmtNum(t.seconds)}</td>
								<td class="error">{t.error ?? ''}</td>
							</tr>
						{/snippet}
					</VirtualTable>
					{#if s.proptest}
						<h2>Property tests ({fmtNum(s.proptest.cases ?? null)} cases)</h2>
						{#if s.proptest.error}<p class="error">{s.proptest.error}</p>{/if}
						<ul class="props">
							{#each Object.entries(s.proptest.properties ?? {}) as [p, v] (p)}
								<li class="state"><span class="swatch s-{v}"></span>{p}: {v}</li>
							{/each}
						</ul>
					{:else}
						<p class="muted">No property-test run in this version.</p>
					{/if}
				{/snippet}
			</Shard>
		{/snippet}
	</SourcePage>
{/key}

<style>
	.props {
		list-style: none;
		padding: 0;
		columns: 2 260px;
	}
	.props li {
		display: flex;
	}
</style>
