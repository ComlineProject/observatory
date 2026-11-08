<script lang="ts">
	import { page } from '$app/state';
	import CiPage from '$lib/CiPage.svelte';
	let id = $derived(page.params.source ?? '');
</script>

{#key id}
	<CiPage {id} />
{/key}
