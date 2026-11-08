<script lang="ts">
	// A small single-series line; nulls break the line.
	let { values, label }: { values: (number | null | undefined)[]; label: string } = $props();
	const W = 160,
		H = 36;
	let path = $derived.by(() => {
		const xs = values.map((v, i) => [i, v] as const).filter(([, v]) => v != null) as [number, number][];
		if (xs.length < 2) return '';
		let lo = Infinity,
			hi = -Infinity;
		for (const [, v] of xs) ((lo = Math.min(lo, v)), (hi = Math.max(hi, v)));
		const span = hi - lo || 1;
		const n = values.length - 1 || 1;
		let d = '',
			pen = false;
		values.forEach((v, i) => {
			if (v == null) return void (pen = false);
			const x = (i / n) * (W - 4) + 2,
				y = H - 3 - ((v - lo) / span) * (H - 6);
			d += `${pen ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
			pen = true;
		});
		return d;
	});
</script>

{#if path}
	<svg width={W} height={H} viewBox="0 0 {W} {H}" role="img" aria-label={label}>
		<path d={path} fill="none" stroke="var(--series-1)" stroke-width="2" stroke-linejoin="round" />
	</svg>
{/if}
