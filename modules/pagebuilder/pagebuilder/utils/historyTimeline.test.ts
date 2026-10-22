import { describe, expect, it } from 'vitest';

import { buildHistory } from './historyTimeline';
import type { PageRestoreMarker, PageRevisionRead } from './types';

const revision = (id: number, created_at: string): PageRevisionRead => ({
  id,
  page_id: 1,
  title: `r${id}`,
  meta_description: null,
  og_image: null,
  event: 'publish',
  note: null,
  created_at,
  created_by: null,
});

const marker = (snapshot_id: number, restored_at: string): PageRestoreMarker => ({
  import_id: snapshot_id,
  snapshot_id,
  change: 'overwritten',
  restored_at,
  restored_by: 'admin',
});

const shape = (entries: ReturnType<typeof buildHistory>) =>
  entries.map((e) => (e.kind === 'revision' ? `r${e.revision.id}` : `s${e.marker.snapshot_id}`));

describe('buildHistory', () => {
  it('reads a zone-less revision time as UTC, whatever the viewer zone', () => {
    const tz = process.env.TZ;
    process.env.TZ = 'Europe/Berlin';
    try {
      // 10:00 UTC revision; the restore was 08:30 UTC. Read as Berlin local
      // time the revision would be 08:00 UTC and sort below the marker.
      const entries = buildHistory(
        [revision(2, '2026-10-02T10:00:00')],
        [marker(7, '2026-10-02T10:30:00+02:00')],
      );
      expect(shape(entries)).toEqual(['r2', 's7']);
    } finally {
      if (tz === undefined) delete process.env.TZ;
      else process.env.TZ = tz;
    }
  });

  it('interleaves markers by time, newest first', () => {
    const entries = buildHistory(
      [revision(3, '2026-10-03T00:00:00Z'), revision(1, '2026-10-01T00:00:00Z')],
      [marker(7, '2026-10-02T00:00:00Z'), marker(9, '2026-10-04T00:00:00Z')],
    );
    expect(shape(entries)).toEqual(['s9', 'r3', 's7', 'r1']);
  });

  it('compares a revision with the next older revision, skipping markers', () => {
    const entries = buildHistory(
      [revision(3, '2026-10-03T00:00:00Z'), revision(1, '2026-10-01T00:00:00Z')],
      [marker(7, '2026-10-02T00:00:00Z')],
    );
    const first = entries[0];
    expect(first.kind === 'revision' && first.previous?.id).toBe(1);
    const last = entries[2];
    expect(last.kind === 'revision' && last.previous).toBeUndefined();
  });

  it('keeps markers older than every revision, and markers alone', () => {
    expect(
      shape(
        buildHistory([revision(1, '2026-10-05T00:00:00Z')], [marker(2, '2026-10-01T00:00:00Z')]),
      ),
    ).toEqual(['r1', 's2']);
    expect(shape(buildHistory([], [marker(2, '2026-10-01T00:00:00Z')]))).toEqual(['s2']);
  });

  it('keeps the server order of revisions even when timestamps disagree', () => {
    const entries = buildHistory(
      [revision(5, '2026-10-01T00:00:00Z'), revision(4, '2026-10-02T00:00:00Z')],
      [],
    );
    expect(shape(entries)).toEqual(['r5', 'r4']);
  });
});
