<script lang="ts">
	import { page } from '$app/state';
	import SourcePage from '$lib/SourcePage.svelte';
	import BenchChart from '$lib/BenchChart.svelte';
	import Shard from '$lib/Shard.svelte';
	import VirtualTable from '$lib/VirtualTable.svelte';
	import { fmtNum } from '$lib/data.svelte';

	type BenchShard = { benches: Record<string, Record<string, number | null>> };
	let id = $derived(page.params.source ?? '');
	function flat(s: BenchShard) {
		return Object.entries(s.benches).flatMap(([k, ms]) => Object.entries(ms).map(([m, v]) => ({ k, m, v })));
	}
</script>

{#key id}
	<SourcePage {id} heading="Benchmarks">
		{#snippet chart(src, ctx)}
			<BenchChart {src} {ctx} />
		{/snippet}
		{#snippet detail(src, vi)}
			<Shard {src} {vi}>
				{#snippet children(s: BenchShard)}
					<VirtualTable rows={flat(s)} height={360}>
						{#snippet header()}<tr><th>benchmark</th><th>metric</th><th class="num">value</th></tr>{/snippet}
						{#snippet row(r: { k: string; m: string; v: number | null })}
							<tr><td title={r.k}>{r.k}</td><td>{r.m}</td><td class="num">{fmtNum(r.v)}</td></tr>
						{/snippet}
					</VirtualTable>
				{/snippet}
			</Shard>
		{/snippet}
	</SourcePage>
{/key}
