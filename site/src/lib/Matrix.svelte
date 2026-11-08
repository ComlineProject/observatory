<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { UrlState } from './url.svelte';
	import { loadManifest, loadSource, mark, shortCommit, shortDate, type ManifestSource, type Source, type Value } from './data.svelte';
	import VersionPicker, { type PickItem } from './VersionPicker.svelte';
	import VirtualTable from './VirtualTable.svelte';

	interface CellInfo {
		state: string | null;
		proven_by: string[] | null;
		note: string | null;
		tracking: string | null;
		failing: string[] | null;
	}
	type ConfShard = { subjects: Record<string, Record<string, CellInfo>> };
	interface Column {
		k: number;
		subject: string;
		title: string;
		rows: Map<string, number>;
	}

	let { matrix }: { matrix: string } = $props();
	const url = new UrlState(['at', 'a', 'b', 'v', 'cell']);
	let srcs = $state<Source[]>([]);
	let unpublished = $state<ManifestSource[]>([]);
	let err = $state('');
	let loaded = $state(false);

	onMount(() => {
		const m = untrack(() => matrix);
		loadManifest()
			.then(async (man) => {
				const mine = man.sources.filter((s) => s.kind === 'conformance' && s.matrix === m);
				unpublished = mine.filter((s) => s.status !== 'ok');
				const ok = await Promise.all(
					mine
						.filter((s) => s.status === 'ok')
						.map((s) =>
							loadSource(s.id).then(
								async (x) => (await x.loadInitial(), x),
								(e) => ((unpublished = [...unpublished, { ...s, reason: String(e.message ?? e) }]), null)
							)
						)
				);
				srcs = ok.filter((x): x is Source => !!x);
				loaded = true;
			})
			.catch((e) => (err = String(e)));
	});

	// Columns: every subject of every source on this matrix.
	let columns = $derived.by(() => {
		const out: Column[] = [];
		srcs.forEach((s, k) => {
			const by = new Map<string, Map<string, number>>();
			s.index.metrics.forEach((m, i) => {
				const cut = m.key.indexOf('/');
				const subj = m.key.slice(0, cut),
					feat = m.key.slice(cut + 1);
				if (!by.has(subj)) by.set(subj, new Map());
				by.get(subj)!.set(feat, i);
			});
			for (const [subject, rows] of by) out.push({ k, subject, title: srcs.length > 1 && by.size > 1 ? `${subject} (${s.index.title})` : subject, rows });
		});
		return out;
	});
	let features = $derived.by(() => {
		const seen = new Map<string, { title: string; description: string }>();
		for (const s of srcs) for (const [id, f] of Object.entries(s.index.features ?? {})) if (!seen.has(id)) seen.set(id, f);
		for (const c of columns) for (const f of c.rows.keys()) if (!seen.has(f)) seen.set(f, { title: f, description: '' });
		// Titles may carry Markdown code spans; show them as plain text.
		return [...seen.entries()].map(([id, f]) => ({ id, title: f.title.replaceAll('`', ''), description: f.description }));
	});

	// Versions of every source, merged by date. A matrix version is a point in time:
	// each source at its newest version published by then.
	let items = $derived.by(() => {
		const all: PickItem[] = [];
		for (const s of srcs)
			for (const v of s.index.versions)
				all.push({
					key: `${s.index.id}:${v.label}`,
					label: v.label,
					date: v.date,
					commit: v.commit,
					release: !!v.release,
					cycle: v.cycle,
					repoUrl: s.index.repo_url,
					note: srcs.length > 1 ? s.index.title : undefined
				});
		return all.sort((x, y) => (x.date < y.date ? -1 : x.date > y.date ? 1 : 0));
	});
	function dateOf(key: string | null): string | null {
		if (!key) return null;
		return items.find((i) => i.key === key)?.date ?? null;
	}
	function versionAt(s: Source, t: string | null): number | null {
		const vs = s.index.versions;
		if (t === null) return vs.length - 1;
		let lo = 0,
			hi = vs.length - 1,
			ans = -1;
		while (lo <= hi) {
			const mid = (lo + hi) >> 1;
			if (vs[mid].date <= t) ((ans = mid), (lo = mid + 1));
			else hi = mid - 1;
		}
		return ans < 0 ? null : ans;
	}
	let mode = $derived(url.get('a') !== null || url.get('b') !== null ? 'compare' : url.get('v') !== null ? 'multi' : 'matrix');
	let atKey = $derived(url.get('at') ?? items.at(-1)?.key ?? null);
	let atVs = $derived(srcs.map((s) => versionAt(s, dateOf(atKey))));
	let aVs = $derived(srcs.map((s) => versionAt(s, dateOf(url.get('a')))));
	let bVs = $derived(srcs.map((s) => versionAt(s, dateOf(url.get('b')))));
	let multiKeys = $derived((url.get('v') ?? '').split(',').filter((k) => items.some((i) => i.key === k)));

	$effect(() => {
		const want: [Source, number | null][] = [];
		srcs.forEach((s, k) => {
			want.push([s, atVs[k]]);
			if (mode === 'compare') want.push([s, aVs[k]], [s, bVs[k]]);
		});
		if (mode === 'multi') for (const key of multiKeys) srcs.forEach((s) => want.push([s, versionAt(s, dateOf(key))]));
		for (const [s, v] of want) if (v !== null) s.loadVersion(v);
	});

	function stateOf(c: Column, feat: string, vi: number | null): Value | undefined {
		if (vi === null) return null;
		const i = c.rows.get(feat);
		if (i === undefined) return null;
		void srcs[c.k].rev;
		return srcs[c.k].columns[i][vi];
	}

	// The opened cell: "<column index>/<feature>"
	let cell = $derived.by(() => {
		const c = url.get('cell');
		if (!c) return null;
		const cut = c.indexOf('/');
		const col = columns.find((x) => `${srcs[x.k].index.id}.${x.subject}` === c.slice(0, cut));
		return col ? { col, feat: c.slice(cut + 1) } : null;
	});
	function openCell(c: Column, feat: string) {
		url.set({ cell: `${srcs[c.k].index.id}.${c.subject}/${feat}` });
	}
	let cellShard = $state<CellInfo | null>(null);
	let cellShardFor = $state('');
	$effect(() => {
		if (!cell) return;
		const s = srcs[cell.col.k],
			vi = atVs[cell.col.k];
		if (vi === null) return;
		const key = `${s.index.id}/${vi}/${cell.col.subject}/${cell.feat}`;
		const { subject } = cell.col,
			feat = cell.feat;
		s.shard<ConfShard>(vi).then((sh) => {
			cellShard = sh.subjects?.[subject]?.[feat] ?? null;
			cellShardFor = key;
		});
		s.loadAll(); // the timeline needs every version
	});
	let timeline = $derived.by(() => {
		if (!cell) return [];
		const s = srcs[cell.col.k];
		void s.rev;
		const i = cell.col.rows.get(cell.feat);
		if (i === undefined) return [];
		const out: { vi: number; from: Value | undefined; to: Value | undefined }[] = [];
		let prev: Value | undefined = undefined;
		let seen = false;
		s.columns[i].forEach((v, vi) => {
			if (v === undefined) return;
			if (!seen || v !== prev) out.push({ vi, from: seen ? prev : undefined, to: v });
			prev = v;
			seen = true;
		});
		return out;
	});

	// Compare: changed cells plus proven_by case ids added / removed.
	interface Diff {
		col: string;
		feat: string;
		sa: Value | undefined;
		sb: Value | undefined;
		added: string[];
		removed: string[];
	}
	let shardsAB = $state<{ key: string; a: (ConfShard | null)[]; b: (ConfShard | null)[] } | null>(null);
	$effect(() => {
		if (mode !== 'compare') return;
		const key = JSON.stringify([aVs, bVs]);
		const get = (s: Source, v: number | null) => (v === null ? Promise.resolve(null) : s.shard<ConfShard>(v));
		const ss = srcs;
		const av = aVs,
			bv = bVs;
		Promise.all([Promise.all(ss.map((s, k) => get(s, av[k]))), Promise.all(ss.map((s, k) => get(s, bv[k])))]).then(([a, b]) => (shardsAB = { key, a, b }));
	});
	let diffs = $derived.by(() => {
		if (mode !== 'compare') return [];
		const out: Diff[] = [];
		const sh = shardsAB && shardsAB.key === JSON.stringify([aVs, bVs]) ? shardsAB : null;
		for (const c of columns)
			for (const f of features) {
				if (!c.rows.has(f.id)) continue;
				const sa = stateOf(c, f.id, aVs[c.k]),
					sb = stateOf(c, f.id, bVs[c.k]);
				const pa = new Set(sh?.a[c.k]?.subjects?.[c.subject]?.[f.id]?.proven_by ?? []);
				const pb = new Set(sh?.b[c.k]?.subjects?.[c.subject]?.[f.id]?.proven_by ?? []);
				const added = [...pb].filter((x) => !pa.has(x)),
					removed = [...pa].filter((x) => !pb.has(x));
				if ((sa ?? null) !== (sb ?? null) || added.length || removed.length) out.push({ col: c.title, feat: f.title, sa, sb, added, removed });
			}
		return out;
	});
	$effect(() => {
		void diffs;
		if (mode === 'compare' && performance.getEntriesByName('pick-input').length) {
			mark('compare-done');
			performance.measure('compare-switch', 'pick-input', 'compare-done');
			performance.clearMarks('pick-input');
		}
	});

	function setMode(m: string) {
		const last = items.at(-1)?.key ?? null;
		if (m === 'matrix') url.set({ a: null, b: null, v: null });
		else if (m === 'compare') {
			const rels = items.filter((i) => i.release && i.key !== last);
			url.set({ a: url.get('a') ?? rels.at(-1)?.key ?? items.at(-2)?.key ?? last, b: url.get('b') ?? last, v: null });
		} else {
			const rels = items.filter((i) => i.release).map((i) => i.key);
			url.set({ a: null, b: null, v: [...new Set([...rels, last])].join(',') });
		}
	}
	function itemLabel(key: string | null) {
		const i = items.find((x) => x.key === key);
		return i ? i.label + (i.note ? ` (${i.note})` : '') : '';
	}
	const isUrl = (s: string) => /^https?:\/\//.test(s);
</script>

<svelte:head><title>{matrix} conformance · Comline Observatory</title></svelte:head>

<h1>Conformance: {matrix}</h1>
<p class="secondary">
	{matrix === 'wire' ? 'Wire features × runtimes.' : matrix === 'codegen' ? 'Generator features × target languages.' : ''}
	Each cell is what the producer's own conformance run proved.
</p>
{#if err}<p class="error">{err}</p>{/if}
{#each unpublished as u (u.id)}
	<p class="muted">{u.title}: not published yet ({u.reason})</p>
{/each}

<div class="row" role="tablist">
	<button role="tab" class:on={mode === 'matrix'} aria-selected={mode === 'matrix'} onclick={() => setMode('matrix')}>Matrix</button>
	<button role="tab" class:on={mode === 'compare'} aria-selected={mode === 'compare'} onclick={() => setMode('compare')}>Compare A / B</button>
	<button role="tab" class:on={mode === 'multi'} aria-selected={mode === 'multi'} onclick={() => setMode('multi')}>N versions</button>
</div>

<p class="legend muted">
	{#each ['supported', 'partial', 'ignored', 'unsupported'] as st (st)}<span class="state"><span class="swatch s-{st}"></span>{st}</span>{/each}
	<span class="state"><span class="swatch s-none"></span>not listed</span>
</p>

{#if !loaded}
	{#if !err}<p class="muted">loading…</p>{/if}
{:else if srcs.length === 0}
	<p class="muted">No source on this matrix is published yet.</p>
{:else if mode === 'matrix'}
	<div class="row">
		<span>at</span>
		<VersionPicker name="at" {items} value={atKey} onpick={(k) => url.set({ at: k })} />
		{#each srcs as s, k (s.index.id)}
			{#if atVs[k] !== null}
				{@const v = s.index.versions[atVs[k]!]}
				<span class="muted">{s.index.title}: {v.label} · <a class="mono" href="{s.index.repo_url}/commit/{v.commit}">{shortCommit(v.commit)}</a></span>
			{:else}
				<span class="muted">{s.index.title}: nothing published yet</span>
			{/if}
		{/each}
	</div>
	<div class="scroll">
		<table class="matrix">
			<thead>
				<tr><th>feature</th>{#each columns as c (c.k + c.subject)}<th>{c.title}</th>{/each}</tr>
			</thead>
			<tbody>
				{#each features as f (f.id)}
					<tr>
						<th title={f.description}>{f.title}</th>
						{#each columns as c (c.k + c.subject)}
							{@const st = stateOf(c, f.id, atVs[c.k])}
							{@const open = cell?.col === c && cell?.feat === f.id}
							<td>
								<button class="cellbtn" class:open onclick={() => openCell(c, f.id)} aria-label="{f.title}, {c.title}: {st ?? 'not listed'}">
									<span class="swatch s-{st ?? 'none'}"></span>{st ?? '–'}
								</button>
							</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	</div>

	{#if cell}
		{@const s = srcs[cell.col.k]}
		{@const vi = atVs[cell.col.k]}
		{@const key = `${s.index.id}/${vi}/${cell.col.subject}/${cell.feat}`}
		<section class="panel" data-testid="cell-detail">
			<div class="row" style="justify-content: space-between">
				<h2 style="margin: 0">{cell.feat} · {cell.col.title}{vi !== null ? ` at ${s.index.versions[vi].label}` : ''}</h2>
				<button onclick={() => url.set({ cell: null })}>close</button>
			</div>
			{#if cellShardFor !== key}
				<p class="muted">loading…</p>
			{:else if !cellShard}
				<p class="muted">Not listed at this version.</p>
			{:else}
				<dl>
					<dt>state</dt><dd class="state"><span class="swatch s-{cellShard.state ?? 'none'}"></span>{cellShard.state ?? '–'}</dd>
					<dt>proven by</dt><dd>{#if cellShard.proven_by?.length}{#each cellShard.proven_by as p (p)}<code>{p}</code> {/each}{:else}–{/if}</dd>
					<dt>note</dt><dd>{cellShard.note ?? '–'}</dd>
					<dt>tracking</dt><dd>{#if cellShard.tracking}{#if isUrl(cellShard.tracking)}<a href={cellShard.tracking}>{cellShard.tracking}</a>{:else}{cellShard.tracking}{/if}{:else}–{/if}</dd>
					<dt>failing</dt><dd>{#if cellShard.failing?.length}{#each cellShard.failing as p (p)}<code>{p}</code> {/each}{:else}–{/if}</dd>
				</dl>
			{/if}
			<h2>State changes</h2>
			<ol class="timeline">
				{#each timeline as t (t.vi)}
					{@const v = s.index.versions[t.vi]}
					<li>
						<button class="link" onclick={() => url.set({ at: `${s.index.id}:${v.label}` })}>{v.label}</button>
						<span class="muted">{shortDate(v.date)}</span>
						{#if t.from !== undefined}<span class="state"><span class="swatch s-{t.from ?? 'none'}"></span>{t.from ?? 'not listed'}</span> →{/if}
						<span class="state"><span class="swatch s-{t.to ?? 'none'}"></span>{t.to ?? 'not listed'}</span>
					</li>
				{/each}
			</ol>
		</section>
	{/if}
{:else if mode === 'compare'}
	<div class="row">
		<span>A</span>
		<VersionPicker name="a" {items} value={url.get('a')} onpick={(k) => url.set({ a: k })} />
		<span>B</span>
		<VersionPicker name="b" {items} value={url.get('b')} onpick={(k) => url.set({ b: k })} />
	</div>
	<p class="muted">Cells whose state or proving cases changed between {itemLabel(url.get('a'))} and {itemLabel(url.get('b'))}.</p>
	<div data-testid="delta-table">
		<VirtualTable rows={diffs} height={480} empty="No cell changed.">
			{#snippet header()}<tr><th>column</th><th>feature</th><th>A</th><th>B</th><th>cases added</th><th>cases removed</th></tr>{/snippet}
			{#snippet row(d: Diff)}
				<tr>
					<td>{d.col}</td>
					<td>{d.feat}</td>
					<td><span class="state"><span class="swatch s-{d.sa ?? 'none'}"></span>{d.sa ?? '–'}</span></td>
					<td><span class="state"><span class="swatch s-{d.sb ?? 'none'}"></span>{d.sb ?? '–'}</span></td>
					<td title={d.added.join(', ')}>{d.added.length ? '+ ' + d.added.join(', ') : ''}</td>
					<td title={d.removed.join(', ')}>{d.removed.length ? '− ' + d.removed.join(', ') : ''}</td>
				</tr>
			{/snippet}
		</VirtualTable>
	</div>
{:else}
	<div class="row">
		<button onclick={() => url.set({ v: items.filter((i) => i.release).map((i) => i.key).join(',') || (items.at(-1)?.key ?? null) })}>all releases</button>
		<span>add</span>
		<VersionPicker name="add" {items} value={null} onpick={(k) => url.set({ v: [...new Set([...multiKeys, k])].sort((x, y) => ((dateOf(x) ?? '') < (dateOf(y) ?? '') ? -1 : 1)).join(',') })} />
	</div>
	<div class="scroll">
		<table class="matrix">
			<thead>
				<tr><th>feature</th><th>column</th>{#each multiKeys as k (k)}<th>{itemLabel(k)}</th>{/each}</tr>
			</thead>
			<tbody>
				{#each features as f (f.id)}
					{#each columns.filter((c) => c.rows.has(f.id)) as c (c.k + c.subject)}
						<tr>
							<th>{f.title}</th>
							<td>{c.title}</td>
							{#each multiKeys as k (k)}
								{@const st = stateOf(c, f.id, versionAt(srcs[c.k], dateOf(k)))}
								<td><span class="state"><span class="swatch s-{st ?? 'none'}"></span>{st ?? '–'}</span></td>
							{/each}
						</tr>
					{/each}
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<style>
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 14px;
		font-size: 12px;
	}
	.scroll {
		overflow: auto;
		max-width: 100%;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface-1);
	}
	.matrix {
		border-collapse: collapse;
		width: 100%;
	}
	.matrix th,
	.matrix td {
		padding: 2px 8px;
		border-bottom: 1px solid var(--grid);
		text-align: left;
		white-space: nowrap;
		font-weight: normal;
	}
	.matrix thead th {
		position: sticky;
		top: 0;
		background: var(--surface-2);
		font-weight: 600;
	}
	.cellbtn {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		border: 1px solid transparent;
		background: transparent;
		padding: 2px 6px;
	}
	.cellbtn.open {
		border-color: var(--text-muted);
	}
	dl {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 4px 12px;
	}
	dt {
		color: var(--text-muted);
	}
	dd {
		margin: 0;
	}
	code {
		font-size: 12px;
		background: var(--surface-2);
		padding: 0 4px;
		border-radius: 3px;
	}
	.timeline {
		padding-left: 18px;
	}
	.timeline li {
		display: flex;
		gap: 10px;
		align-items: center;
		flex-wrap: wrap;
	}
	.link {
		border: 0;
		background: none;
		color: var(--link);
		text-decoration: underline;
		padding: 0;
	}
</style>
