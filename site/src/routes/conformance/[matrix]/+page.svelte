<script lang="ts">
	import { page } from '$app/state';
	import Matrix from '$lib/Matrix.svelte';
	let matrix = $derived(page.params.matrix ?? '');
</script>

{#key matrix}
	<Matrix {matrix} />
{/key}
