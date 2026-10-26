import { describe, expect, it } from 'vitest';

import type { ApplyResult, SectionLabels, Snapshot } from '../../utils/snapshotsApi';
import type { PageRestoreMarker } from '../../utils/types';
import {
  appliedSections,
  countParts,
  deniedSections,
  restoredWith,
  sectionContents,
  snapshotFootnote,
} from './sectionSummary';

// Counts as the list, the approve result and the history marker show them.
// The host merges every module's catalogue (tests/vitest-i18n.ts does the
// same), so news' own keys resolve here; pagebuilder never names them itself.
const NEWS: SectionLabels = {
  section: 'news',
  label_key: 'news.bundle.title',
  count_label_keys: {
    articles: 'news.bundle.counts.articles',
    tags: 'news.bundle.counts.tags',
    created: 'news.bundle.counts.created',
  },
};

describe('countParts', () => {
  it("names each kind by the section's key, and an unknown one by its kind", () => {
    expect(countParts({ articles: 4, extra: 1 }, NEWS.count_label_keys)).toBe(
      'Articles: 4 · extra: 1',
    );
  });

  it('can leave out zeros', () => {
    expect(countParts({ articles: 0, tags: 2 }, NEWS.count_label_keys, { skipZero: true })).toBe(
      'Tags: 2',
    );
  });

  it("follows the section's declared order, not the stored one", () => {
    expect(countParts({ extra: 1, tags: 2, articles: 4 }, NEWS.count_label_keys)).toBe(
      'Articles: 4 · Tags: 2 · extra: 1',
    );
  });
});

describe('sectionContents', () => {
  const snapshot = (manifest: Partial<Snapshot['manifest']>): Snapshot => ({
    id: 1,
    note: null,
    source: 'manual',
    format_version: 2,
    size_bytes: 1,
    created_at: null,
    created_by: null,
    manifest: {
      format_version: 2,
      created_at: '2026-10-26T00:00:00+00:00',
      pages: [],
      layout: { header: 0, footer: 0 },
      counts: { pages: 1, redirects: 0, media: 0 },
      missing_media: [],
      ...manifest,
    },
  });

  it("lists each contributed section's counts, not pagebuilder's own", () => {
    const lines = sectionContents(
      snapshot({
        contents: [
          { section: 'pagebuilder', counts: { pages: 1 } },
          { section: 'news', counts: { articles: 3, tags: 1 } },
          { section: 'shop', counts: { products: 2 } },
        ],
      }),
      [NEWS],
    );
    expect(lines).toEqual(['News — Articles: 3 · Tags: 1', 'shop — products: 2']);
  });

  it('says what the capture left out', () => {
    const lines = sectionContents(
      snapshot({
        omitted: [{ section: 'news', label_key: 'news.bundle.title', permissions: ['news.edit'] }],
      }),
      [NEWS],
    );
    expect(lines).toEqual([
      'News is not in this snapshot: whoever took it did not hold news.edit.',
    ]);
  });

  it('is empty for a snapshot from before sections', () => {
    expect(sectionContents(snapshot({}), [NEWS])).toEqual([]);
  });
});

describe('the approve result', () => {
  const result: ApplyResult = {
    pages_created: 0,
    pages_updated: 1,
    media_added: 0,
    redirects: 0,
    redirects_dropped: [],
    sections: { news: { articles: 2, created: 1, tags: 0 } },
    denied_sections: [],
  };

  it('names what each section wrote, without the zeros', () => {
    expect(appliedSections(result, [NEWS])).toEqual(['News: Articles: 2 · Articles created: 1']);
  });

  it('names a section the restore left out', () => {
    expect(
      deniedSections({
        ...result,
        denied_sections: [
          { section: 'news', label_key: 'news.bundle.title', permissions: ['news.publish'] },
        ],
      }),
    ).toEqual([
      'News is left out of this restore: restoring it needs news.publish. The pages restore as usual.',
    ]);
  });
});

describe('restoredWith', () => {
  const marker = (sections: PageRestoreMarker['sections']): PageRestoreMarker => ({
    import_id: 1,
    snapshot_id: 2,
    change: 'overwritten',
    restored_at: '2026-10-26T00:00:00Z',
    restored_by: null,
    sections,
  });

  it('counts what the same restore wrote elsewhere', () => {
    expect(
      restoredWith(marker([{ section: 'news', label_key: 'news.bundle.title', count: 3 }])),
    ).toBe('The same restore also changed: News (3)');
  });

  it('says nothing for a pages-only restore', () => {
    expect(restoredWith(marker([]))).toBeNull();
    expect(restoredWith(marker(undefined))).toBeNull();
  });
});

describe('snapshotFootnote', () => {
  it('names the contributed sections when there are any', () => {
    expect(snapshotFootnote([NEWS])).toMatch(/a snapshot carries News\. Branding is not/);
    expect(snapshotFootnote([])).toMatch(/Branding and other modules' content are not part/);
  });
});
