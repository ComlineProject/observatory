<script lang="ts" module>
	export interface PickItem {
		/** The value written to the URL. */
		key: string;
		label: string;
		date: string;
		commit: string;
		release: boolean;
		cycle: string;
		repoUrl: string;
		/** Extra text, e.g. the source on a combined matrix. */
		note?: string;
	}
</script>

<script lang="ts">
	import { mark, shortCommit, shortDate } from './data.svelte';

	let {
		items,
		value,
		onpick,
		name = 'version'
	}: { items: PickItem[]; value: string | null; onpick: (key: string) => void; name?: string } = $props();

	let open = $state(false);
	let dev = $state(false);
	let current = $derived(items.find((i) => i.key === value));

	// Releases, plus the newest version so there's always something to pick.
	let shown = $derived.by(() => {
		if (dev) return items;
		const last = items.at(-1);
		return items.filter((i) => i.release || i === last);
	});
	let groups = $derived.by(() => {
		const out: { cycle: string; items: PickItem[] }[] = [];
		for (const i of shown) {
			const g = out.at(-1);
			if (dev && g && g.cycle === i.cycle) g.items.push(i);
			else if (dev || !g) out.push({ cycle: i.cycle, items: [i] });
			else g.items.push(i);
		}
		return out.reverse().map((g) => ({ ...g, items: [...g.items].reverse() }));
	});

	function pick(k: string) {
		mark('pick-input');
		open = false;
		onpick(k);
	}
</script>

<div class="picker">
	<button
		type="button"
		class="trigger"
		aria-haspopup="listbox"
		aria-expanded={open}
		data-picker={name}
		onclick={() => (open = !open)}
	>
		<span class="lab">{current ? current.label : 'choose…'}</span>
		{#if current}<span class="muted">{shortDate(current.date)}</span>{/if}
		<span aria-hidden="true">▾</span>
	</button>
	{#if open}
		<div class="pop" role="listbox" aria-label={name}>
			<label class="devtoggle"><input type="checkbox" bind:checked={dev} /> show dev versions</label>
			<div class="list">
				{#each groups as g (g.cycle)}
					{#if dev}<div class="cyc">{g.cycle === 'unreleased' ? 'unreleased' : `→ ${g.cycle}`}</div>{/if}
					{#each g.items as i (i.key)}
						<div class="item" class:sel={i.key === value} class:rel={i.release}>
							<button type="button" role="option" aria-selected={i.key === value} onclick={() => pick(i.key)}>
								<span class="lab">{i.label}</span>
								{#if i.release}<span class="badge">release</span>{/if}
								{#if i.note}<span class="muted">{i.note}</span>{/if}
								<span class="muted">{shortDate(i.date)}</span>
							</button>
							<a class="commit" href="{i.repoUrl}/commit/{i.commit}" target="_blank" rel="noreferrer">{shortCommit(i.commit)}</a>
						</div>
					{/each}
				{/each}
			</div>
		</div>
	{/if}
</div>

<style>
	.picker {
		position: relative;
		display: inline-block;
	}
	.trigger {
		display: inline-flex;
		gap: 8px;
		align-items: baseline;
	}
	.lab {
		font-variant-numeric: tabular-nums;
	}
	.pop {
		position: absolute;
		z-index: 20;
		top: calc(100% + 4px);
		left: 0;
		min-width: 340px;
		max-width: calc(100vw - 32px);
		background: var(--surface-1);
		border: 1px solid var(--border);
		border-radius: 6px;
		box-shadow: 0 6px 24px rgb(0 0 0 / 0.18);
	}
	.devtoggle {
		display: block;
		padding: 8px 10px;
		border-bottom: 1px solid var(--grid);
	}
	.list {
		max-height: 360px;
		overflow: auto;
	}
	.cyc {
		padding: 6px 10px 2px;
		font-size: 12px;
		color: var(--text-muted);
		font-weight: 600;
	}
	.item {
		display: flex;
		align-items: center;
	}
	.item > button {
		flex: 1;
		display: flex;
		gap: 8px;
		align-items: baseline;
		text-align: left;
		border: 0;
		border-radius: 0;
		background: transparent;
		padding: 4px 10px;
	}
	.item:hover,
	.item.sel {
		background: var(--surface-2);
	}
	.item.sel .lab {
		font-weight: 700;
	}
	.commit {
		font-family: ui-monospace, monospace;
		font-size: 12px;
		padding: 0 10px;
	}
	.badge {
		font-size: 11px;
		padding: 0 5px;
		border-radius: 4px;
		border: 1px solid var(--border);
		color: var(--text-secondary);
	}
</style>
