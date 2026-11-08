// Reads the dataset described in DATA.md (format 1) and nothing else.
// Every file is fetched at most once and kept in memory.
import { base } from '$app/paths';

export type Kind = 'bench' | 'fuzz' | 'conformance' | 'size' | 'coverage' | 'compile' | 'ci';

/** Navigation order and the name of each kind's section. */
export const KINDS: { kind: Kind; label: string }[] = [
	{ kind: 'bench', label: 'Benchmarks' },
	{ kind: 'fuzz', label: 'Fuzzing' },
	{ kind: 'conformance', label: 'Conformance' },
	{ kind: 'size', label: 'Size' },
	{ kind: 'coverage', label: 'Coverage' },
	{ kind: 'compile', label: 'Compile' },
	{ kind: 'ci', label: 'CI' }
];
export const kindLabel = (k: string) => KINDS.find((x) => x.kind === k)?.label ?? k;
export type Value = number | string | null;

export interface ManifestSource {
	id: string;
	kind: Kind;
	title: string;
	repo: string;
	matrix: string | null;
	status: 'ok' | 'unpublished';
	index?: string;
	reason?: string;
}
export interface Manifest {
	format: number;
	generated: string;
	sources: ManifestSource[];
	/** The overview cards' data: one small file (DATA.md "Summary"). */
	summary: string;
}
export interface CardSummary {
	label: string;
	date: string;
	release: string | null;
	spark: (number | null)[];
	sparkLabel: string;
	badge: { text: string; cls: string } | null;
}
export interface Version {
	id: string;
	commit: string;
	date: string;
	cycle: string;
	label: string;
	release: string | null;
	run: string | null;
	toolchain: string | null;
	shard: string;
}
export interface Cycle {
	id: string;
	tag: string | null;
	date: string | null;
	chunk: string;
}
export interface Metric {
	key: string;
	metric: string;
	unit: string | null;
	type: 'number' | 'verdict' | 'state';
	group: string | null;
	param: number | null;
	/** Which way is better (DATA.md); derived from the kind when absent. */
	better?: 'higher' | 'lower' | null;
}
export interface Index {
	id: string;
	kind: Kind;
	title: string;
	repo: string;
	repo_url: string;
	branch: string;
	path: string;
	matrix: string | null;
	versions: Version[];
	cycles: Cycle[];
	releases: string;
	metrics: Metric[];
	features: Record<string, { title: string; description: string }> | null;
}
interface Chunk {
	versions: number[];
	values: Value[][];
}

export const FORMAT = 1;

const files = new Map<string, Promise<unknown>>();

/** Fetch a path relative to the dataset root, once. */
export function fetchData<T>(path: string): Promise<T> {
	let p = files.get(path);
	if (!p) {
		p = fetch(`${base}/data/${path}`).then((r) => {
			if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
			return r.json();
		});
		p.catch(() => files.delete(path));
		files.set(path, p);
	}
	return p as Promise<T>;
}

export function loadManifest(): Promise<Manifest> {
	return fetchData<Manifest>('manifest.json').then((m) => {
		if (m.format !== FORMAT) throw new Error(`dataset format ${m.format}, this site reads ${FORMAT}`);
		return m;
	});
}

/** Every ok source's card, keyed by source id. */
export function loadSummary(): Promise<Record<string, CardSummary>> {
	return loadManifest().then((m) => fetchData<{ sources: Record<string, CardSummary> }>(m.summary)).then((x) => x.sources);
}

/**
 * One source: its index plus every chunk loaded so far, merged into one
 * full-length column per metric. `undefined` = not loaded yet, `null` = the
 * version has no value.
 */
export class Source {
	index: Index;
	columns: (Value | undefined)[][];
	/** Bumped whenever a chunk lands, so derived views recompute. */
	rev = $state(0);
	private loaded = new Set<string>();
	private pending = new Map<string, Promise<void>>();
	byLabel = new Map<string, number>();
	cycleOf: number[];
	releaseIdx: number[];

	constructor(index: Index) {
		this.index = index;
		this.multiMetric = index.kind !== 'fuzz' && index.kind !== 'ci' && new Set(index.metrics.map((m) => m.metric)).size > 1;
		const n = index.versions.length;
		this.columns = index.metrics.map(() => new Array(n));
		index.versions.forEach((v, i) => this.byLabel.set(v.label, i));
		const cyc = new Map(index.cycles.map((c, i) => [c.id, i]));
		this.cycleOf = index.versions.map((v) => cyc.get(v.cycle) ?? -1);
		this.releaseIdx = index.versions.flatMap((v, i) => (v.release ? [i] : []));
	}

	private loadChunk(path: string): Promise<void> {
		if (this.loaded.has(path)) return Promise.resolve();
		let p = this.pending.get(path);
		if (!p) {
			p = fetchData<Chunk>(path).then((c) => {
				const cols = this.columns;
				for (let i = 0; i < c.values.length && i < cols.length; i++) {
					const row = c.values[i];
					const col = cols[i];
					for (let j = 0; j < c.versions.length; j++) col[c.versions[j]] = row[j];
				}
				this.loaded.add(path);
				this.pending.delete(path);
				this.rev++;
			});
			this.pending.set(path, p);
		}
		return p;
	}

	cycleLoaded(ci: number): boolean {
		return this.loaded.has(this.index.cycles[ci]?.chunk);
	}
	loadReleases() {
		return this.loadChunk(this.index.releases);
	}
	loadCycle(ci: number) {
		const c = this.index.cycles[ci];
		return c ? this.loadChunk(c.chunk) : Promise.resolve();
	}
	/** The initial set: releases plus the newest cycle. */
	loadInitial() {
		return Promise.all([this.loadReleases(), this.loadCycle(this.index.cycles.length - 1)]);
	}
	loadAll() {
		return Promise.all(this.index.cycles.map((_, i) => this.loadCycle(i)));
	}
	/** Load the cycles touching versions [lo, hi]. */
	loadRange(lo: number, hi: number) {
		const a = this.cycleOf[Math.max(0, lo)] ?? 0;
		const b = this.cycleOf[Math.min(this.cycleOf.length - 1, hi)] ?? 0;
		const ps = [];
		for (let c = a; c <= b; c++) ps.push(this.loadCycle(c));
		return Promise.all(ps);
	}
	loadVersion(vi: number) {
		const v = this.index.versions[vi];
		if (!v) return Promise.resolve();
		if (v.release && this.loaded.has(this.index.releases)) return Promise.resolve();
		return this.loadCycle(this.cycleOf[vi]);
	}
	hasVersion(vi: number) {
		const v = this.index.versions[vi];
		return !!v && (this.cycleLoaded(this.cycleOf[vi]) || (!!v.release && this.loaded.has(this.index.releases)));
	}
	shard<T>(vi: number): Promise<T> {
		return fetchData<T>(this.index.versions[vi].shard);
	}
	/** Index range [lo, hi] of a cycle's versions. */
	cycleRange(ci: number): [number, number] {
		let lo = -1,
			hi = -1;
		for (let i = 0; i < this.cycleOf.length; i++)
			if (this.cycleOf[i] === ci) {
				if (lo < 0) lo = i;
				hi = i;
			}
		return [lo, hi];
	}
	/** More than one metric name (a bench with e.g. `instructions` and `instructions-opt`). */
	multiMetric: boolean;
	/** A row's name: the key, with the metric when it isn't the plain instruction count or the source has several. */
	nameOf(m: Metric): string {
		return this.multiMetric ? `${m.key} · ${m.metric}` : metricName(m);
	}
	latest() {
		return this.index.versions.length - 1;
	}
}

const sources = new Map<string, Promise<Source>>();
export async function loadSource(id: string): Promise<Source> {
	let p = sources.get(id);
	if (!p) {
		p = loadManifest().then(async (m) => {
			const s = m.sources.find((x) => x.id === id);
			if (!s) throw new Error(`no source "${id}" in the manifest`);
			if (s.status !== 'ok' || !s.index) throw new Error(`"${s.title}" isn't published yet: ${s.reason ?? 'no reason given'}`);
			return new Source(await fetchData<Index>(s.index));
		});
		p.catch(() => sources.delete(id));
		sources.set(id, p);
	}
	return p;
}

export function shortCommit(c: string) {
	return c.slice(0, 8);
}
export function shortDate(d: string | null) {
	return d ? d.slice(0, 10) : '';
}
export function metricName(m: Metric) {
	return m.metric === 'instructions' ? m.key : `${m.key} · ${m.metric}`;
}
export function fmtNum(v: Value | undefined): string {
	if (v === null || v === undefined) return '–';
	if (typeof v === 'string') return v;
	return v.toLocaleString('en-US');
}
/** DATA.md "Which way is better": `better` when the collector wrote it, else derived from the kind. */
export function betterOf(m: Metric, kind: Kind): 'higher' | 'lower' | null {
	if (m.better !== undefined) return m.better;
	if (m.type !== 'number') return null;
	if (kind === 'coverage' || (kind === 'fuzz' && (m.metric === 'executions' || m.metric === 'corpus'))) return 'higher';
	return 'lower';
}
/** 1 when an increase is a regression, -1 when a decrease is, 0 when neither. */
export function directionOf(m: Metric, kind: Kind): number {
	const b = betterOf(m, kind);
	return b === 'lower' ? 1 : b === 'higher' ? -1 : 0;
}

/** A value in its metric's unit: bytes as KB/MB, seconds, percentages. */
export function fmtUnit(v: Value | undefined, unit: string | null, signed = false): string {
	if (v === null || v === undefined) return '–';
	if (typeof v === 'string') return v;
	const sign = signed && v > 0 ? '+' : '';
	if (unit === 'bytes') {
		const a = Math.abs(v);
		const [d, u] = a >= 1e9 ? [1e9, 'GB'] : a >= 1e6 ? [1e6, 'MB'] : a >= 1e3 ? [1e3, 'KB'] : [1, 'B'];
		return `${sign}${(v / d).toLocaleString('en-US', { maximumFractionDigits: d === 1 ? 0 : 2 })} ${u}`;
	}
	if (unit === 's') return `${sign}${v.toLocaleString('en-US', { maximumFractionDigits: 2 })} s`;
	if (unit === 'pp') return `${sign}${v.toLocaleString('en-US', { maximumFractionDigits: 2 })} pp`;
	if (unit === '%') return `${sign}${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}%`;
	return sign + v.toLocaleString('en-US');
}
/** Axis tick: compact, in the unit. */
const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 });
export function fmtAxis(v: number, unit: string | null): string {
	if (unit === 'bytes' || unit === 's' || unit === '%') return fmtUnit(v, unit);
	return compact.format(v);
}
export function unitLabel(unit: string | null): string {
	return unit === 's' ? 'seconds' : unit === '%' ? 'percent' : (unit ?? '');
}

export function fmtPct(p: number | null): string {
	if (p === null || !isFinite(p)) return '–';
	return `${p > 0 ? '+' : ''}${p.toFixed(2)}%`;
}

/** Marks for the budget test. */
export function mark(name: string) {
	if (typeof performance !== 'undefined') performance.mark(name);
}
