<script lang="ts">
	// N versions side by side: one column per chosen version.
	import VirtualTable from './VirtualTable.svelte';
	import { fmtUnit, type Source, type Value } from './data.svelte';

	let { src, vs, group = '', text = '' }: { src: Source; vs: number[]; group?: string; text?: string } = $props();

	interface Row {
		name: string;
		unit: string | null;
		vals: (Value | undefined)[];
	}
	let rows = $derived.by(() => {
		void src.rev;
		const t = text.toLowerCase();
		const out: Row[] = [];
		src.index.metrics.forEach((m, i) => {
			if (group && m.group !== group && !(m.group ?? '').startsWith(group + '/')) return;
			const name = src.nameOf(m);
			if (t && !name.toLowerCase().includes(t)) return;
			out.push({ name, unit: m.unit, vals: vs.map((v) => src.columns[i][v]) });
		});
		return out;
	});
</script>

<VirtualTable {rows} height={480}>
	{#snippet header()}
		<tr>
			<th>metric</th>
			{#each vs as v (v)}<th class="num">{src.index.versions[v].label}</th>{/each}
		</tr>
	{/snippet}
	{#snippet row(r: Row)}
		<tr>
			<td title={r.name}>{r.name}</td>
			{#each r.vals as x, k (k)}
				<td class="num">
					{#if typeof x === 'string'}<span class="state"><span class="swatch s-{x}"></span>{x}</span>{:else}{fmtUnit(x, r.unit)}{/if}
				</td>
			{/each}
		</tr>
	{/snippet}
</VirtualTable>
