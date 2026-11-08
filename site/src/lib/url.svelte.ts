// Page selection kept in the URL (shareable; back/forward work). Values are
// mirrored into local state so an input updates the view synchronously and the
// URL follows.
import { page } from '$app/state';
import { goto } from '$app/navigation';

export class UrlState {
	values = $state<Record<string, string | null>>({});
	ready = $state(false);

	constructor(keys: string[]) {
		$effect(() => {
			const sp = page.url.searchParams;
			for (const k of keys) this.values[k] = sp.get(k);
			this.ready = true;
		});
	}

	get(k: string): string | null {
		return this.values[k] ?? null;
	}

	set(upd: Record<string, string | null>) {
		Object.assign(this.values, upd);
		const u = new URL(page.url);
		for (const [k, v] of Object.entries(upd)) {
			if (v === null || v === '') u.searchParams.delete(k);
			else u.searchParams.set(k, v);
		}
		const q = u.searchParams.toString().replaceAll('%2C', ',').replaceAll('%3A', ':').replaceAll('%2F', '/').replaceAll('%7E', '~').replaceAll('%40', '@');
		goto(u.pathname + (q ? '?' + q : ''), { keepFocus: true, noScroll: true });
	}
}
