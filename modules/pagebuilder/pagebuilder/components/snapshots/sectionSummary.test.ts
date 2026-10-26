import { describe, expect, it } from 'vitest';

import type { ImportPlan, SectionPlanEntry } from '../../utils/snapshotsApi';
import { overwritesAnything, overwriteWarning } from './planSummary';
import { lineItems, lineLabel, sectionLabel, sectionMarker, sectionNotes } from './sectionSummary';

// The host merges every module's catalogue (tests/vitest-i18n.ts does the
// same), so news' own keys resolve here; pagebuilder never names them itself.
// Counts, the list and the approve result: sectionCounts.test.ts.

function plan(overrides: Partial<ImportPlan> = {}): ImportPlan {
  return {
    pages: { new: [], overwritten: [], unchanged: [], untouched: [] },
    layout: { header: 0, footer: 0 },
    redirects: { added: [], removed: [], dropped: [] },
    ...overrides,
  };
}

function entry(overrides: Partial<SectionPlanEntry> = {}): SectionPlanEntry {
  return {
    section: 'news',
    label_key: 'news.bundle.title',
    lines: [
      {
        label_key: 'news.bundle.plan.overwritten',
        count: 2,
        items: [],
        tone: 'warning',
      },
    ],
    overwrites: 2,
    ...overrides,
  };
}

describe('sectionLabel', () => {
  it("resolves the contributor's own key", () => {
    expect(sectionLabel('news.bundle.title', 'news')).toBe('News');
  });

  it('falls back to the raw name, never a dotted key', () => {
    expect(sectionLabel('notes.bundle.title', 'notes')).toBe('notes');
    expect(sectionLabel(null, 'notes')).toBe('notes');
  });
});

describe('lineLabel', () => {
  it("resolves the contributor's line key", () => {
    expect(lineLabel('news.bundle.plan.overwritten')).toBe('Articles overwritten');
  });

  it("reads as words when the contributor's catalogue is gone", () => {
    expect(lineLabel('gone.bundle.plan.redirects_dropped')).toBe('redirects dropped');
  });
});

describe('overwriteWarning with sections', () => {
  it("adds a section's overwrites to the pages'", () => {
    const withNews = plan({
      pages: { new: [], overwritten: [{ slug: 'a', title: 'A' }], unchanged: [], untouched: [] },
      sections: [entry()],
    });
    expect(overwriteWarning(withNews)).toBe(
      '3 items will be overwritten, counting pages and the content below.',
    );
    expect(overwritesAnything(withNews)).toBe(true);
  });

  it('still warns when only contributed rows are at stake', () => {
    expect(overwritesAnything(plan({ sections: [entry()] }))).toBe(true);
    expect(overwritesAnything(plan({ sections: [entry({ overwrites: 0 })] }))).toBe(false);
  });
});

describe('sectionMarker', () => {
  it('says why a redacted reader sees counts only, naming the permissions', () => {
    const text = sectionMarker(entry({ redacted: true, permissions: ['news.edit'] }));
    expect(text).toBe('News: only the counts are shown here. Seeing the details needs news.edit.');
  });

  it('says when the details could not be read', () => {
    expect(sectionMarker(entry({ details_unavailable: true }))).toMatch(
      /^News: the details of this plan could not be read/,
    );
  });

  it('is silent for a reader who sees the rows', () => {
    expect(sectionMarker(entry())).toBeNull();
  });

  it('says a section with nothing to do changes nothing, instead of an empty card', () => {
    const idle = entry({ lines: [{ label_key: 'news.bundle.plan.new', count: 0, items: [] }] });
    expect(sectionMarker(idle)).toBe(
      'This bundle carries News content, but restoring it changes nothing.',
    );
  });
});

describe('lineItems', () => {
  it("keeps each row's language and resolves its note key", () => {
    const [item] = lineItems({
      label_key: 'news.bundle.plan.redirects_dropped',
      count: 1,
      items: [{ title: 'old', slug: 'old', locale: null, note_key: 'news.bundle.plan.tags' }],
    });
    expect(item).toMatchObject({ title: 'old', slug: 'old', detail: 'Tags' });
  });
});

describe('sectionNotes', () => {
  it('lists denied, skipped and absent sections, warnings first', () => {
    const notes = sectionNotes(
      plan({
        denied: [
          {
            section: 'news',
            label_key: 'news.bundle.title',
            permissions: ['news.edit', 'news.publish'],
          },
        ],
        skipped: [{ section: 'shop', version: 1 }],
        absent: [{ section: 'notes', label_key: 'notes.bundle.title' }],
      }),
    );
    expect(notes.map((n) => [n.tone, n.text])).toEqual([
      [
        'warning',
        'News is left out of this restore: restoring it needs news.edit, news.publish. The pages restore as usual.',
      ],
      [
        'warning',
        'This bundle also carries shop content, which this site cannot restore. It will be skipped.',
      ],
      ['muted', 'notes is not in this bundle and stays as it is.'],
    ]);
  });

  it('says a section was left out at capture, and why', () => {
    const [note] = sectionNotes(
      plan({
        absent: [
          {
            section: 'news',
            label_key: 'news.bundle.title',
            omitted: true,
            permissions: ['news.edit'],
          },
        ],
      }),
    );
    expect(note.text).toMatch(/^News was left out of this snapshot: .*news\.edit/);
  });
});
