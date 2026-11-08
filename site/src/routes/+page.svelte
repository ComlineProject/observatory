<script lang="ts">
	import { base } from '$app/paths';
	import { onMount } from 'svelte';
	import SourceCards from '$lib/SourceCards.svelte';
	import { KINDS, loadManifest, type ManifestSource } from '$lib/data.svelte';

	let sources = $state<ManifestSource[]>([]);
	let err = $state('');
	onMount(() => {
		loadManifest().then(
			(m) => (sources = m.sources),
			(e) => (err = String(e))
		);
	});
	let groups = $derived(KINDS.map((k) => ({ ...k, list: sources.filter((s) => s.kind === k.kind) })).filter((g) => g.list.length));
	let twoBenches = $derived(sources.filter((s) => s.kind === 'bench' && s.status === 'ok').length >= 2);
</script>

<svelte:head><title>Comline Observatory</title></svelte:head>

<h1>Comline Observatory</h1>
<p class="secondary">Benchmarks, fuzzing, conformance, size, coverage, compile times and CI over every published version.</p>
{#if err}<p class="error">{err}</p>{/if}

{#each groups as g (g.kind)}
	<h2 class="kind-h"><a href="{base}/{g.kind}/">{g.label}</a></h2>
	<SourceCards sources={g.list} ratio={g.kind === 'bench' && twoBenches} />
{/each}

<style>
	.kind-h {
		margin-top: 24px;
	}
	.kind-h a {
		color: inherit;
		text-decoration: none;
	}
	.kind-h a:hover {
		text-decoration: underline;
	}
</style>
