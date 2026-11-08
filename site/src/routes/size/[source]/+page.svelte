<script lang="ts">
	import { page } from '$app/state';
	import MetricPage from '$lib/MetricPage.svelte';
	let id = $derived(page.params.source ?? '');
</script>

{#key id}
	<MetricPage {id} kind="size" />
{/key}
