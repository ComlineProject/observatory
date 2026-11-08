<script lang="ts" module>
	import type { Value } from './data.svelte';
	export interface StripCell {
		v: Value | undefined;
		/** e.g. the version label */
		label: string;
		vi: number;
		/** drawn with a ring (a CI rerun) */
		ring?: boolean;
	}
</script>

<script lang="ts">
	// One row of pass / fail / no-verdict cells per item; a cell opens its version.
	let {
		rows,
		onpick,
		ringLabel = ''
	}: { rows: { name: string; cells: StripCell[] }[]; onpick: (vi: number) => void; ringLabel?: string } = $props();
</script>

<div class="strip panel">
	{#each rows as r (r.name)}
		<div class="srow">
			<span class="pname" title={r.name}>{r.name}</span>
			<span class="cells" style:grid-template-columns="repeat({Math.max(1, r.cells.length)}, minmax(3px, 1fr))">
				{#each r.cells as c, k (k)}
					{@const t = `${c.label}: ${c.v ?? 'no verdict'}${c.ring ? ` (${ringLabel})` : ''}`}
					<button class="cell swatch s-{c.v ?? 'none'}" class:ring={c.ring} title={t} aria-label="{r.name} at {t}" onclick={() => onpick(c.vi)}></button>
				{/each}
			</span>
		</div>
	{/each}
</div>

<style>
	.srow {
		display: grid;
		grid-template-columns: minmax(120px, 240px) 1fr;
		gap: 8px;
		align-items: center;
		margin: 2px 0;
	}
	.pname {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 12px;
	}
	.cells {
		display: grid;
		gap: 1px;
	}
	.cell {
		width: auto;
		height: 14px;
		padding: 0;
		border: 0;
		border-radius: 1px;
	}
	.cell.s-none {
		border: 1px dashed var(--text-muted);
	}
	.cell.ring {
		outline: 2px solid var(--text-primary);
		outline-offset: -2px;
	}
</style>
