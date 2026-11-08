<script lang="ts" generics="T">
	// Only the visible rows (plus a small overscan) are in the DOM.
	import type { Snippet } from 'svelte';

	let {
		rows,
		rowHeight = 28,
		height = 420,
		header,
		row,
		empty = 'Nothing to show.'
	}: {
		rows: T[];
		rowHeight?: number;
		height?: number;
		header: Snippet;
		row: Snippet<[T, number]>;
		empty?: string;
	} = $props();

	let scrollTop = $state(0);
	const overscan = 8;
	let start = $derived(Math.max(0, Math.floor(scrollTop / rowHeight) - overscan));
	let end = $derived(Math.min(rows.length, Math.ceil((scrollTop + height) / rowHeight) + overscan));
	let visible = $derived(rows.slice(start, end));
</script>

<div class="vt" style:max-height="{height}px" onscroll={(e) => (scrollTop = e.currentTarget.scrollTop)}>
	<table>
		<thead>{@render header()}</thead>
		<tbody>
			{#if rows.length === 0}
				<tr><td class="muted" colspan="99">{empty}</td></tr>
			{:else}
				<tr style:height="{start * rowHeight}px" aria-hidden="true"></tr>
				{#each visible as r, i (start + i)}
					{@render row(r, start + i)}
				{/each}
				<tr style:height="{(rows.length - end) * rowHeight}px" aria-hidden="true"></tr>
			{/if}
		</tbody>
	</table>
</div>
<p class="count muted">{rows.length.toLocaleString('en-US')} rows</p>

<style>
	.vt {
		overflow: auto;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface-1);
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
	}
	:global(.vt thead th) {
		position: sticky;
		top: 0;
		background: var(--surface-2);
		text-align: left;
		font-weight: 600;
		padding: 4px 8px;
		border-bottom: 1px solid var(--grid);
		white-space: nowrap;
		z-index: 1;
	}
	:global(.vt tbody td) {
		padding: 0 8px;
		height: 27px;
		border-bottom: 1px solid var(--grid);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 520px;
	}
	:global(.vt td.num, .vt th.num) {
		text-align: right;
	}
	.count {
		margin: 4px 0 0;
		font-size: 12px;
	}
</style>
