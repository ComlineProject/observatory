<script lang="ts">
	import '../app.css';
	import { base } from '$app/paths';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { loadManifest, type ManifestSource } from '$lib/data.svelte';

	let { children } = $props();
	let sources = $state<ManifestSource[]>([]);
	onMount(() => {
		loadManifest().then((m) => (sources = m.sources), () => {});
	});

	let nav = $derived([
		{ href: '/', label: 'Overview' },
		...sources
			.filter((s) => s.kind !== 'conformance' && s.status === 'ok')
			.map((s) => ({ href: `/${s.kind}/${s.id}/`, label: `${s.kind === 'bench' ? 'Benchmarks' : 'Fuzzing'}: ${s.title}` })),
		{ href: '/conformance/wire/', label: 'Wire conformance' },
		{ href: '/conformance/codegen/', label: 'Codegen conformance' }
	]);
	let path = $derived(page.url.pathname.slice(base.length) || '/');
</script>

<header>
	<a class="brand" href="{base}/">Comline Observatory</a>
	<nav>
		{#each nav as n (n.href)}
			<a href="{base}{n.href}" class:active={n.href === '/' ? path === '/' : path.startsWith(n.href)}>{n.label}</a>
		{/each}
	</nav>
</header>
<main>
	{@render children()}
</main>

<style>
	header {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 20px;
		align-items: center;
		padding: 10px 16px;
		border-bottom: 1px solid var(--border);
		background: var(--surface-1);
	}
	.brand {
		font-weight: 700;
		color: var(--text-primary);
		text-decoration: none;
	}
	nav {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 14px;
	}
	nav a {
		color: var(--text-secondary);
		text-decoration: none;
		padding: 2px 0;
		border-bottom: 2px solid transparent;
	}
	nav a.active {
		color: var(--text-primary);
		border-bottom-color: var(--series-1);
	}
	main {
		max-width: 1200px;
		margin: 0 auto;
		padding: 16px;
	}
</style>
