import { describe, expect, it } from 'vitest';

import type { ImportPlan, Snapshot } from '../../utils/snapshotsApi';
import {
  contentsLine,
  missingMediaWarning,
  overwriteWarning,
  planTotals,
  sourceLabel,
  untouchedNote,
} from './planSummary';

function plan(overrides: Partial<ImportPlan['pages']> = {}, redirects = {}): ImportPlan {
  return {
    pages: { new: [], overwritten: [], unchanged: [], untouched: [], ...overrides },
    layout: { header: 0, footer: 0 },
    redirects: { added: [], removed: [], dropped: [], ...redirects },
  };
}

function snapshot(overrides: Partial<Snapshot> = {}): Snapshot {
  return {
    id: 1,
    note: null,
    source: 'manual',
    format_version: 1,
    size_bytes: 100,
    created_at: null,
    created_by: null,
    manifest: {
      format_version: 1,
      created_at: '2026-08-28T00:00:00+00:00',
      pages: [],
      layout: { header: 0, footer: 0 },
      counts: { pages: 12, redirects: 3, media: 11 },
      missing_media: [],
    },
    ...overrides,
  };
}

describe('overwriteWarning', () => {
  it('says nothing alarming when nothing is at risk', () => {
    expect(overwriteWarning(plan())).toBe('No existing page will be overwritten.');
  });

  it('is singular for one page', () => {
    expect(overwriteWarning(plan({ overwritten: [{ slug: 'home', title: 'Home' }] }))).toBe(
      '1 page will be overwritten.',
    );
  });

  it('leads with the count for several', () => {
    const p = plan({
      overwritten: [
        { slug: 'a', title: 'A' },
        { slug: 'b', title: 'B' },
      ],
    });
    expect(overwriteWarning(p)).toBe('2 pages will be overwritten.');
  });
});

describe('untouchedNote', () => {
  it('is absent when the bundle covers everything', () => {
    expect(untouchedNote(plan())).toBeNull();
  });

  it('says plainly that nothing is deleted', () => {
    const note = untouchedNote(plan({ untouched: [{ slug: 'legacy', title: 'Legacy' }] }));
    expect(note).toContain('will not be deleted');
    expect(note).toContain('1 page is');
  });

  it('pluralises', () => {
    const note = untouchedNote(
      plan({
        untouched: [
          { slug: 'a', title: 'A' },
          { slug: 'b', title: 'B' },
        ],
      }),
    );
    expect(note).toContain('2 pages are');
  });
});

describe('planTotals', () => {
  it('counts every bucket', () => {
    const totals = planTotals(
      plan({ new: [{ slug: 'n', title: 'N' }] }, { added: ['old'], dropped: ['orphan'] }),
    );
    expect(totals.created).toBe(1);
    expect(totals.redirectsAdded).toBe(1);
    expect(totals.redirectsDropped).toBe(1);
  });
});

describe('contentsLine', () => {
  it('summarises what a snapshot holds', () => {
    expect(contentsLine(snapshot())).toBe('12 pages · 3 redirects · 11 media');
  });

  it('is singular where it should be', () => {
    const one = snapshot({
      manifest: {
        ...snapshot().manifest,
        counts: { pages: 1, redirects: 1, media: 0 },
      },
    });
    expect(contentsLine(one)).toBe('1 page · 1 redirect · 0 media');
  });
});

describe('sourceLabel', () => {
  it('explains where a snapshot came from', () => {
    expect(sourceLabel('pre_restore')).toBe('Automatic, before a restore');
    expect(sourceLabel('upload')).toBe('Uploaded');
  });
});

describe('missingMediaWarning', () => {
  it('is absent for a clean capture', () => {
    expect(missingMediaWarning(snapshot())).toBeNull();
  });

  it('names the files, because restoring would silently lose them', () => {
    const s = snapshot({
      manifest: { ...snapshot().manifest, missing_media: ['hero.jpg'] },
    });
    expect(missingMediaWarning(s)).toContain('hero.jpg');
  });
});
