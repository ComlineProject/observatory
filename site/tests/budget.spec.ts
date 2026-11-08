import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';

const DATA = new URL('../build/data/', import.meta.url);
const manifest = JSON.parse(readFileSync(new URL('manifest.json', DATA), 'utf8')) as {
	sources: { id: string; kind: string; matrix: string | null; status: string; index?: string }[];
};
const ok = manifest.sources.filter((s) => s.status === 'ok');
const bench = ok.find((s) => s.kind === 'bench');
const twoBench = ok.filter((s) => s.kind === 'bench').length >= 2;
const fuzz = ok.find((s) => s.kind === 'fuzz');
const matrices = [...new Set(ok.filter((s) => s.kind === 'conformance').map((s) => s.matrix!))];

const FCP_MS = 1000;
const SWITCH_MS = 50;
const DATA_BYTES = 500 * 1024;

const gz = new Map<string, number>();
function gzipSize(path: string) {
	let n = gz.get(path);
	if (n === undefined) gz.set(path, (n = gzipSync(readFileSync(new URL(path, DATA)), { level: 6 }).length));
	return n;
}

/** Open a page; return FCP and the compressed size of data fetched before it rendered. */
async function open(page: Page, path: string, chart: boolean) {
	const fetched: string[] = [];
	let rendered = false;
	page.on('request', (r) => {
		const m = new URL(r.url()).pathname.match(/\/data\/(.+)$/);
		if (m && !rendered) fetched.push(m[1]);
	});
	await page.goto(path);
	if (chart) await page.waitForFunction(() => (window as unknown as { __chartRendered?: number }).__chartRendered !== undefined);
	else await page.waitForLoadState('networkidle');
	rendered = true;
	const fcp = await page.evaluate(() => performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? Infinity);
	const bytes = [...new Set(fetched)].reduce((n, p) => n + gzipSize(p), 0);
	return { fcp, bytes, files: fetched.length };
}

const pages: [string, string, boolean][] = [
	['overview', '', false],
	...(bench ? [['bench', `bench/${bench.id}/`, true] as [string, string, boolean]] : []),
	...(twoBench ? [['ratio', 'ratio/', false] as [string, string, boolean]] : []),
	...(fuzz ? [['fuzz', `fuzz/${fuzz.id}/`, true] as [string, string, boolean]] : []),
	...matrices.map((m) => [`conformance ${m}`, `conformance/${m}/`, false] as [string, string, boolean])
];

for (const [name, path, chart] of pages) {
	test(`${name}: first paint and initial data`, async ({ page }) => {
		const r = await open(page, path, chart);
		console.log(`${name}: FCP ${r.fcp.toFixed(0)} ms, initial data ${(r.bytes / 1024).toFixed(1)} KB gzip in ${r.files} files`);
		expect(r.fcp).toBeLessThan(FCP_MS);
		expect(r.bytes).toBeLessThan(DATA_BYTES);
	});
}

test('bench: switching compare A or B', async ({ page }) => {
	test.skip(!bench, 'no bench source');
	const index = JSON.parse(readFileSync(new URL(bench!.index!, DATA), 'utf8')) as { versions: { label: string; release: string | null }[] };
	const vs = index.versions;
	const releases = vs.filter((v) => v.release).map((v) => v.label);
	const latest = vs.at(-1)!.label;
	const prev = vs.at(-2)!.label;
	await page.goto(`bench/${bench!.id}/?a=${prev}&b=${latest}`);
	await expect(page.getByTestId('delta-table')).toBeVisible();
	await page.waitForLoadState('networkidle');

	// Picks that stay inside the loaded data (releases chunk + newest cycle), alternating A and B.
	const picks: ['a' | 'b', string][] = [];
	for (const r of releases.slice(-3)) picks.push(['a', r]);
	picks.push(['b', prev], ['b', latest], ['a', prev]);
	const times: number[] = [];
	for (const [side, label] of picks) {
		await page.locator(`[data-picker="${side}"]`).click();
		const opt = page.locator('[role="listbox"] [role="option"]', { hasText: new RegExp(`^${label.replace(/[.+]/g, '\\$&')}\\b`) }).first();
		if (!(await opt.count())) {
			await page.locator('[role="listbox"] input[type="checkbox"]').check();
		}
		await page.evaluate(() => performance.clearMeasures('compare-switch'));
		await opt.click();
		const d = await page.waitForFunction(() => performance.getEntriesByName('compare-switch')[0]?.duration, undefined, { timeout: 5000 });
		times.push((await d.jsonValue()) as number);
	}
	console.log(`compare switch: ${times.map((t) => t.toFixed(1)).join(', ')} ms`);
	expect(Math.max(...times)).toBeLessThan(SWITCH_MS);
});
