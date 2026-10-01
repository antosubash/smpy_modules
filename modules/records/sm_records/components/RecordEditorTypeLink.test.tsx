import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import '../test-dom';

vi.mock('@inertiajs/react', () => ({
  Link: ({ children, href }: { children?: unknown; href: string }) => (
    <a href={href}>{children as React.ReactNode}</a>
  ),
}));

const { RecordEditorTypeLink } = await import('./RecordEditorTypeLink');

describe('RecordEditorTypeLink — U14: the type label is a link back to its list', () => {
  it('links to the record list, not plain text', () => {
    const html = renderToStaticMarkup(
      <RecordEditorTypeLink label="QA UX Event" backHref="/admin/records/qa_ux_event" />,
    );
    expect(html).toContain('href="/admin/records/qa_ux_event"');
    expect(html).toContain('QA UX Event');
  });
});
