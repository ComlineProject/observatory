import type { PickItem } from './VersionPicker.svelte';
import type { Source } from './data.svelte';

export function pickItems(s: Source, prefix = '', note?: string): PickItem[] {
	return s.index.versions.map((v) => ({
		key: prefix + v.label,
		label: v.label,
		date: v.date,
		commit: v.commit,
		release: !!v.release,
		cycle: v.cycle,
		repoUrl: s.index.repo_url,
		note
	}));
}

export const SERIES = ['--series-1', '--series-2', '--series-3', '--series-4', '--series-5', '--series-6', '--series-7', '--series-8'];
export const MAX_SERIES = SERIES.length;
