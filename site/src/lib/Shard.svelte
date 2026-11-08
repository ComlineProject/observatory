<script lang="ts" generics="T">
	// Loads one version's shard (only when that version is opened).
	import type { Snippet } from 'svelte';
	import type { Source } from './data.svelte';
	let { src, vi, children }: { src: Source; vi: number; children: Snippet<[T]> } = $props();
	let data = $state<T | null>(null);
	let err = $state('');
	$effect(() => {
		data = null;
		err = '';
		const v = vi;
		src.shard<T>(v).then(
			(d) => v === vi && (data = d),
			(e) => (err = String(e))
		);
	});
</script>

{#if err}<p class="error">{err}</p>{:else if data}{@render children(data)}{:else}<p class="muted">loading…</p>{/if}
