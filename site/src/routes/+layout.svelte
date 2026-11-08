<script lang="ts">
	import '../app.css';
	import { base } from '$app/paths';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { KINDS, loadManifest, type ManifestSource } from '$lib/data.svelte';

	let { children } = $props();
	let sources = $state<ManifestSource[]>([]);
	onMount(() => {
		loadManifest().then((m) => (sources = m.sources), () => {});
	});

	// One link per kind the manifest has a source of.
	let nav = $derived([
		{ href: '/', label: 'Overview' },
		...KINDS.filter((k) => sources.some((s) => s.kind === k.kind)).map((k) => ({ href: `/${k.kind}/`, label: k.label }))
	]);
	function active(href: string) {
		if (href === '/') return path === '/';
		return path.startsWith(href) || (href === '/bench/' && path.startsWith('/ratio/'));
	}
	let path = $derived(page.url.pathname.slice(base.length) || '/');

	// Dark unless the viewer chose light (app.html applies it before paint).
	let light = $state(false);
	onMount(() => (light = document.documentElement.dataset.theme === 'light'));
	function toggleTheme() {
		light = !light;
		if (light) document.documentElement.dataset.theme = 'light';
		else delete document.documentElement.dataset.theme;
		try {
			if (light) localStorage.setItem('theme', 'light');
			else localStorage.removeItem('theme');
		} catch {}
	}
</script>

<header>
	<a class="brand" href="{base}/">Comline Observatory</a>
	<nav>
		{#each nav as n (n.href)}
			<a href="{base}{n.href}" class:active={active(n.href)}>{n.label}</a>
		{/each}
	</nav>
	<button class="theme" onclick={toggleTheme} aria-label={light ? 'Switch to dark theme' : 'Switch to light theme'}>
		{light ? 'Dark' : 'Light'}
	</button>
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
	.theme {
		margin-left: auto;
		font: inherit;
		font-size: 0.85em;
		color: var(--text-secondary);
		background: var(--surface-2);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 2px 10px;
		cursor: pointer;
	}
	main {
		max-width: 1200px;
		margin: 0 auto;
		padding: 16px;
	}
</style>
