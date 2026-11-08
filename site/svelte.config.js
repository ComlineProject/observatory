import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { existsSync, readFileSync } from 'node:fs';

// Prerender a shell for every source the dataset has (DATA.md: manifest.json).
// Sources added later still open through the 404.html fallback.
function entries() {
	const out = ['*', '/conformance/wire/', '/conformance/codegen/'];
	for (const k of ['bench', 'fuzz', 'conformance', 'size', 'coverage', 'compile', 'ci']) out.push(`/${k}/`);
	const file = new URL('./static/data/manifest.json', import.meta.url);
	if (!existsSync(file)) return out;
	for (const s of JSON.parse(readFileSync(file, 'utf8')).sources ?? []) {
		if (s.kind !== 'conformance') out.push(`/${s.kind}/${s.id}/`);
		if (s.kind === 'conformance' && s.matrix) out.push(`/conformance/${s.matrix}/`);
	}
	return [...new Set(out)];
}

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			// GitHub Pages serves this for unknown paths, so a source added after
			// the build still opens (the shell renders client-side).
			fallback: '404.html',
			precompress: false,
			strict: true
		}),
		paths: {
			base: process.argv.includes('dev') ? '' : (process.env.BASE_PATH ?? '')
		},
		prerender: {
			handleMissingId: 'ignore',
			// A kind with no source yet has no page to prerender; the 404.html shell serves it.
			handleUnseenRoutes: 'ignore',
			entries: entries()
		}
	}
};

export default config;
