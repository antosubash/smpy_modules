/** Revisions and restore markers merged into one newest-first history. */

import type { PageRestoreMarker, PageRevisionRead } from './types';

export type HistoryEntry =
  | {
      kind: 'revision';
      revision: PageRevisionRead;
      /** The next-older revision, skipping markers — what Compare diffs against. */
      previous: PageRevisionRead | undefined;
    }
  | { kind: 'restore'; marker: PageRestoreMarker };

const when = (iso: string) => new Date(iso).getTime();

/**
 * Interleave by time. Both inputs arrive newest-first; revisions keep their
 * server order among themselves (id, not timestamp — a restored revision can
 * be newer with older content), and each marker is placed before the first
 * revision older than it. On a tie the revision goes first: the restore stamped
 * its time before applying, so a revision in the same instant came after it.
 */
export function buildHistory(
  revisions: PageRevisionRead[],
  restores: PageRestoreMarker[],
): HistoryEntry[] {
  const markers = [...restores].sort((a, b) => when(b.restored_at) - when(a.restored_at));
  const entries: HistoryEntry[] = [];
  let next = 0;
  revisions.forEach((revision, idx) => {
    while (next < markers.length && when(markers[next].restored_at) > when(revision.created_at)) {
      entries.push({ kind: 'restore', marker: markers[next++] });
    }
    entries.push({ kind: 'revision', revision, previous: revisions[idx + 1] });
  });
  for (; next < markers.length; next++) entries.push({ kind: 'restore', marker: markers[next] });
  return entries;
}
