<script lang="ts">
	// A against B: one array lookup per metric over already-loaded chunks.
	import VirtualTable from './VirtualTable.svelte';
	import { fmtUnit, fmtPct, fmtSpread, mark, type Metric, type Source, type Value } from './data.svelte';

	let {
		src,
		a,
		b,
		group,
		threshold,
		text = '',
		direction = () => 1
	}: {
		src: Source;
		a: number;
		b: number;
		group: string;
		threshold: number;
		text?: string;
		/** 1 when an increase is a regression, -1 when a decrease is, 0 when neither. */
		direction?: (m: Metric) => number;
	} = $props();

	interface Row {
		name: string;
		unit: string | null;
		va: Value | undefined;
		vb: Value | undefined;
		sa: number | null | undefined;
		sb: number | null | undefined;
		d: number | null;
		pct: number | null;
		changed: boolean;
		dir: number;
		/** Regression score: positive = worse. */
		score: number;
	}

	let rows = $derived.by(() => {
		void src.rev;
		const out: Row[] = [];
		const ms = src.index.metrics;
		const t = text.toLowerCase();
		for (let i = 0; i < ms.length; i++) {
			const m = ms[i];
			if (group && m.group !== group && !(m.group ?? '').startsWith(group + '/')) continue;
			const name = src.nameOf(m);
			if (t && !name.toLowerCase().includes(t)) continue;
			const col = src.columns[i];
			const va = col[a],
				vb = col[b];
			const sp = src.spreads[i];
			const sa = sp?.[a],
				sb = sp?.[b];
			if (typeof va === 'number' && typeof vb === 'number') {
				const d = vb - va;
				const pct = va !== 0 ? (d / Math.abs(va)) * 100 : d === 0 ? 0 : null;
				if (threshold > 0 && (pct === null || Math.abs(pct) < threshold)) continue;
				const dir = direction(m);
				out.push({ name, unit: m.unit, va, vb, sa, sb, d, pct, changed: d !== 0, dir, score: pct === null ? (d === 0 ? 0 : Infinity) : pct * (dir || 1) });
			} else {
				const changed = (va ?? null) !== (vb ?? null);
				if (threshold > 0 && !changed) continue;
				out.push({ name, unit: m.unit, va, vb, sa, sb, d: null, pct: null, changed, dir: 0, score: changed ? -1e300 : -Infinity });
			}
		}
		// Largest regression (largest increase) first; non-numeric changes after, unchanged last.
		out.sort((x, y) => (y.score === x.score ? 0 : y.score > x.score ? 1 : -1));
		return out;
	});

	let ready = $derived((void src.rev, src.hasVersion(a) && src.hasVersion(b)));
	$effect(() => {
		void rows;
		if (ready && performance.getEntriesByName('pick-input').length) {
			mark('compare-done');
			performance.measure('compare-switch', 'pick-input', 'compare-done');
			performance.clearMarks('pick-input');
		}
	});
	function cls(p: number | null, dir: number) {
		if (p === null || p === 0 || dir === 0) return '';
		return p * dir > 0 ? 'up-bad' : 'down-good';
	}
</script>

{#if !ready}
	<p class="muted">loading…</p>
{/if}
<div data-testid="delta-table" data-a={a} data-b={b}>
	<VirtualTable {rows} height={480}>
		{#snippet header()}
			<tr><th>metric</th><th class="num">A</th><th class="num">B</th><th class="num">Δ</th><th class="num">Δ%</th></tr>
		{/snippet}
		{#snippet row(r: Row)}
			<tr>
				<td title={r.name}>{r.name}</td>
				<td class="num">{fmtUnit(r.va, r.unit)}{#if r.sa != null}<span class="pm"> {fmtSpread(r.sa)}</span>{/if}</td>
				<td class="num">{fmtUnit(r.vb, r.unit)}{#if r.sb != null}<span class="pm"> {fmtSpread(r.sb)}</span>{/if}</td>
				<td class="num {cls(r.d, r.dir)}">{r.d === null ? (r.changed ? 'changed' : '') : fmtUnit(r.d, r.unit === '%' ? 'pp' : r.unit, true)}</td>
				<td class="num {cls(r.pct, r.dir)}">{fmtPct(r.pct)}</td>
			</tr>
		{/snippet}
	</VirtualTable>
</div>
<p class="muted small">
	Sorted by the largest regression first. Regressions are red, improvements green.{#if src.spreads.some((x) => x)}{' '}
		± is half the reported run-to-run spread: a change inside it can be noise.{/if}
</p>

<style>
	.pm {
		color: var(--text-muted);
		font-size: 11px;
	}
	.small {
		font-size: 12px;
	}
</style>
