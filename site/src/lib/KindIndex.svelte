<script lang="ts">
	// /<kind>/: every source of one kind as a card.
	import { onMount } from 'svelte';
	import SourceCards from './SourceCards.svelte';
	import { kindLabel, loadManifest, type Kind, type ManifestSource } from './data.svelte';

	let { kind }: { kind: Kind } = $props();
	let sources = $state<ManifestSource[] | null>(null);
	let err = $state('');
	onMount(() => {
		loadManifest().then(
			(m) => (sources = m.sources.filter((s) => s.kind === kind)),
			(e) => (err = String(e))
		);
	});
	let ratio = $derived(kind === 'bench' && (sources ?? []).filter((s) => s.status === 'ok').length >= 2);
</script>

<svelte:head><title>{kindLabel(kind)} · Comline Observatory</title></svelte:head>

<h1>{kindLabel(kind)}</h1>
{#if err}<p class="error">{err}</p>{/if}
{#if sources}
	<p class="secondary">{sources.length} {sources.length === 1 ? 'source' : 'sources'}</p>
	{#if sources.length}<SourceCards {sources} {ratio} />{:else}<p class="muted">No sources of this kind.</p>{/if}
{:else if !err}
	<p class="muted">loading…</p>
{/if}
