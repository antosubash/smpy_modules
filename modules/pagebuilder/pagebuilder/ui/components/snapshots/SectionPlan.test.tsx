// @vitest-environment happy-dom
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { ImportPlan } from '../../utils/snapshotsApi';
import { ImportPlanSummary } from './ImportPlanSummary';

(globalThis as unknown as { React: unknown }).React = React;

function plan(overrides: Partial<ImportPlan> = {}): ImportPlan {
  return {
    pages: { new: [], overwritten: [], unchanged: [], untouched: [] },
    layout: { header: 0, footer: 0 },
    redirects: { added: [], removed: [], dropped: [] },
    ...overrides,
  };
}

function render(value: ImportPlan): Document {
  const markup = renderToStaticMarkup(<ImportPlanSummary plan={value} />);
  return new DOMParser().parseFromString(`<div>${markup}</div>`, 'text/html');
}

const NEWS_LINES = [
  {
    label_key: 'news.bundle.plan.overwritten',
    count: 1,
    items: [{ title: 'Hello', slug: 'hello', locale: 'de' }],
    tone: 'warning' as const,
  },
  { label_key: 'news.bundle.plan.new', count: 0, items: [] },
  { label_key: 'news.bundle.plan.categories', count: 2, items: [] },
];

describe('ImportPlanSummary with contributed sections', () => {
  it("renders a section's card from its own keys: title, lines, counts and rows", () => {
    const doc = render(
      plan({
        sections: [
          { section: 'news', label_key: 'news.bundle.title', lines: NEWS_LINES, overwrites: 1 },
        ],
      }),
    );
    const card = doc.querySelector('[data-testid="plan-section-news"]');
    expect(card?.querySelector('h3')?.textContent).toBe('News');
    const headings = [...(card?.querySelectorAll('h3') ?? [])].slice(1).map((h) => h.textContent);
    // An empty line is hidden, like an empty page bucket.
    expect(headings).toEqual(['Articles overwritten (1)', 'Categories (2)']);
    expect(card?.textContent).toContain('Hello');
    expect(card?.textContent).toContain('de');
    expect(card?.querySelector('[data-testid="plan-section-marker"]')).toBeNull();
    // The section's overwrite reaches the headline.
    expect(doc.body.textContent).toContain('1 item will be overwritten');
  });

  it('shows counts and the redaction marker, never rows, to a reader who may not see them', () => {
    const doc = render(
      plan({
        sections: [
          {
            section: 'news',
            label_key: 'news.bundle.title',
            lines: NEWS_LINES.map((line) => ({ ...line, items: [] })),
            overwrites: 1,
            redacted: true,
            permissions: ['news.edit'],
          },
        ],
      }),
    );
    const card = doc.querySelector('[data-testid="plan-section-news"]');
    expect(card?.querySelector('[data-testid="plan-section-marker"]')?.textContent).toBe(
      'News: only the counts are shown here. Seeing the details needs news.edit.',
    );
    expect(card?.textContent).toContain('Articles overwritten (1)');
    expect(card?.querySelector('ul')).toBeNull();
  });

  it('names denied, skipped and absent sections below the cards', () => {
    const doc = render(
      plan({
        denied: [
          {
            section: 'news',
            label_key: 'news.bundle.title',
            permissions: ['news.edit', 'news.publish'],
          },
        ],
        skipped: [{ section: 'shop', version: 1 }],
      }),
    );
    const notes = doc.querySelector('[data-testid="plan-section-notes"]')?.textContent ?? '';
    expect(notes).toContain('News is left out of this restore');
    expect(notes).toContain('This bundle also carries shop content');
  });

  it('renders nothing extra for a pages-only plan', () => {
    const doc = render(plan());
    expect(doc.querySelector('[data-testid^="plan-section"]')).toBeNull();
  });
});
