import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import '../test-dom';

vi.mock('@inertiajs/react', () => ({
  Link: ({ children, href }: { children?: unknown; href: string }) => (
    <a href={href}>{children as React.ReactNode}</a>
  ),
}));

const { RecordListEmpty } = await import('./RecordListEmpty');

describe('RecordListEmpty — U10: a refused filter must not also claim "no match"', () => {
  it('shows the plain "no match" line when the filter simply matched nothing', () => {
    const html = renderToStaticMarkup(
      <RecordListEmpty typeKey="book" trashed={false} filtered onClear={() => {}} />,
    );
    expect(html).toContain('No records match this filter.');
  });

  it('replaces the "no match" line with the real reason once the filter was refused', () => {
    const html = renderToStaticMarkup(
      <RecordListEmpty
        typeKey="book"
        trashed={false}
        filtered
        errorMessage="That value isn't valid for this field."
        onClear={() => {}}
      />,
    );
    expect(html).toContain('That value isn');
    // The two claims are mutually exclusive — nothing was queried, so the
    // box must not also assert that nothing matched.
    expect(html).not.toContain('No records match this filter.');
    expect(html).toContain('data-testid="records-empty-filter-error"');
  });
});

describe('RecordListEmpty — U30: Import is discoverable from a brand-new, empty type', () => {
  it('shows the Import hint next to New record when the caller can edit', () => {
    const html = renderToStaticMarkup(
      <RecordListEmpty
        typeKey="book"
        trashed={false}
        filtered={false}
        canImport
        onClear={() => {}}
      />,
    );
    expect(html).toContain('data-testid="records-empty-import-hint"');
    expect(html).toContain('Import');
  });

  it('says nothing about Import for a caller who cannot edit', () => {
    const html = renderToStaticMarkup(
      <RecordListEmpty typeKey="book" trashed={false} filtered={false} onClear={() => {}} />,
    );
    expect(html).not.toContain('data-testid="records-empty-import-hint"');
  });

  it('says nothing about Import in the filtered or trashed states', () => {
    const filtered = renderToStaticMarkup(
      <RecordListEmpty typeKey="book" trashed={false} filtered canImport onClear={() => {}} />,
    );
    expect(filtered).not.toContain('records-empty-import-hint');
    const trashedHtml = renderToStaticMarkup(
      <RecordListEmpty typeKey="book" trashed filtered={false} canImport onClear={() => {}} />,
    );
    expect(trashedHtml).not.toContain('records-empty-import-hint');
  });
});
