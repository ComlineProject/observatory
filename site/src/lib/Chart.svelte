<script lang="ts" module>
	export interface SeriesSpec {
		label: string;
		/** A CSS custom property name, e.g. `--series-1`. */
		color: string;
	}
	export interface XMark {
		x: number;
		label: string;
	}
	let firstDraw = false;
</script>

<script lang="ts">
	// A uPlot chart. The instance is created once and reused: new data goes in
	// with setData, a changed series set with delSeries/addSeries.
	import uPlot from 'uplot';
	import 'uplot/dist/uPlot.min.css';
	import { onMount, untrack } from 'svelte';
	import { mark } from './data.svelte';

	let {
		xs,
		ys,
		series,
		xLabel = (x: number) => String(x),
		marks = [],
		xRange = null,
		logX = false,
		logY = false,
		height = 320,
		yLabel = '',
		onpick,
		onrange
	}: {
		xs: number[];
		ys: (number | null | undefined)[][];
		series: SeriesSpec[];
		xLabel?: (x: number) => string;
		marks?: XMark[];
		xRange?: [number, number] | null;
		logX?: boolean;
		logY?: boolean;
		height?: number;
		yLabel?: string;
		onpick?: (x: number) => void;
		onrange?: (lo: number, hi: number) => void;
	} = $props();

	let el: HTMLDivElement;
	let u: uPlot | null = null;
	let sig = '';
	let applying = false;
	let theme = $state(0);

	const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 });

	function cssVar(name: string) {
		return getComputedStyle(el).getPropertyValue(name).trim() || '#888';
	}

	function mkSeries(s: SeriesSpec): uPlot.Series {
		const c = cssVar(s.color);
		return {
			label: s.label,
			stroke: c,
			width: 2,
			spanGaps: false,
			points: { size: 7, stroke: c, fill: cssVar('--surface-1'), width: 2 },
			value: (_u, v) => (v == null ? '–' : v.toLocaleString('en-US'))
		};
	}

	function drawMarks(u: uPlot) {
		if (!marks.length) return;
		const ctx = u.ctx;
		const { top, height: h, left, width } = u.bbox;
		ctx.save();
		ctx.strokeStyle = cssVar('--text-muted');
		ctx.fillStyle = cssVar('--text-secondary');
		ctx.lineWidth = devicePixelRatio;
		ctx.setLineDash([4 * devicePixelRatio, 4 * devicePixelRatio]);
		ctx.font = `${11 * devicePixelRatio}px system-ui, sans-serif`;
		ctx.textBaseline = 'top';
		let lastTextEnd = -Infinity;
		for (const m of marks) {
			const x = Math.round(u.valToPos(m.x, 'x', true));
			if (x < left || x > left + width) continue;
			ctx.beginPath();
			ctx.moveTo(x, top);
			ctx.lineTo(x, top + h);
			ctx.stroke();
			const w = ctx.measureText(m.label).width;
			if (x + 3 > lastTextEnd) {
				ctx.fillText(m.label, x + 3 * devicePixelRatio, top + 2 * devicePixelRatio);
				lastTextEnd = x + 3 + w + 6 * devicePixelRatio;
			}
		}
		ctx.restore();
	}

	function opts(): uPlot.Options {
		const ink = cssVar('--text-muted');
		const grid = cssVar('--grid');
		const axis: uPlot.Axis = {
			stroke: ink,
			grid: { stroke: grid, width: 1 },
			ticks: { stroke: grid, width: 1 },
			font: '12px system-ui, sans-serif'
		};
		return {
			width: el.clientWidth || 600,
			height,
			scales: {
				x: logX ? { time: false, distr: 3, log: 2 } : { time: false },
				...(logY ? { y: { distr: 3, log: 10 } } : {})
			},
			axes: [
				{
					...axis,
					space: logX ? 40 : 110,
					incrs: logX ? undefined : [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000],
					values: (_u, splits) => splits.map((x) => (x == null ? '' : xLabel(x)))
				},
				{
					...axis,
					size: 64,
					label: yLabel || undefined,
					values: (_u, splits) => splits.map((v) => (v == null ? '' : compact.format(v)))
				}
			],
			legend: { live: true },
			cursor: { drag: { x: !logX, y: false }, points: { size: 9 } },
			series: [{ label: logX ? 'size' : 'version', value: (_u, v) => (v == null ? '–' : xLabel(v)) }],
			hooks: {
				draw: [
					(u) => {
						drawMarks(u);
						if (!firstDraw && u.data[0]?.length) {
							firstDraw = true;
							mark('chart-rendered');
							(window as unknown as { __chartRendered: number }).__chartRendered = performance.now();
						}
					}
				],
				setScale: [
					(u, key) => {
						if (key !== 'x' || applying || !onrange) return;
						const { min, max } = u.scales.x;
						if (min != null && max != null) onrange(Math.round(min), Math.round(max));
					}
				]
			}
		};
	}

	function create() {
		u?.destroy();
		sig = '';
		u = new uPlot(opts(), [[]], el);
		let down: [number, number] | null = null;
		u.over.addEventListener('mousedown', (e) => (down = [e.clientX, e.clientY]));
		u.over.addEventListener('click', (e) => {
			if (!u || !onpick) return;
			if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
			const i = u.cursor.idx;
			if (i != null) onpick(u.data[0][i]);
		});
		u.over.style.cursor = onpick ? 'pointer' : '';
	}

	function apply() {
		if (!u) return;
		const s = series.map((x) => x.label + '\u0000' + x.color).join('\u0001');
		if (s !== sig) {
			for (let i = u.series.length - 1; i >= 1; i--) u.delSeries(i);
			for (const x of series) u.addSeries(mkSeries(x));
			sig = s;
		}
		applying = true;
		u.setData([xs, ...ys] as uPlot.AlignedData, true);
		if (xRange && xs.length) u.setScale('x', { min: xRange[0], max: xRange[1] });
		applying = false;
	}

	onMount(() => {
		create();
		const ro = new ResizeObserver(() => u?.setSize({ width: el.clientWidth, height }));
		ro.observe(el);
		// The header's toggle switches data-theme on <html>; redraw in its colours.
		const mo = new MutationObserver(() => theme++);
		mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
		return () => {
			ro.disconnect();
			mo.disconnect();
			u?.destroy();
			u = null;
		};
	});

	$effect(() => {
		// Recreate only when the colours change; everything else is setData.
		if (theme > 0) {
			create();
			untrack(apply);
		}
	});

	$effect(() => {
		void [xs, ys, series, xRange, marks];
		apply();
	});
</script>

<div class="chart" bind:this={el}></div>

<style>
	.chart {
		width: 100%;
		min-height: 120px;
	}
	.chart :global(.u-legend) {
		font-size: 12px;
		color: var(--text-secondary);
		text-align: left;
	}
	.chart :global(.u-legend .u-marker) {
		border-radius: 2px;
	}
	.chart :global(.u-select) {
		background: color-mix(in srgb, var(--series-1) 15%, transparent);
	}
</style>
