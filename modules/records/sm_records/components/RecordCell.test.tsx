import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { FieldDef } from '../utils/types';
import { RecordCell } from './RecordCell';

function field(overrides: Partial<FieldDef>): FieldDef {
  return {
    key: 'f',
    type: 'text',
    label: 'F',
    required: false,
    unique: false,
    indexed: true,
    default: null,
    help: null,
    constraints: {},
    options: {},
    ...overrides,
  };
}

function html(f: FieldDef, value: unknown): string {
  return renderToStaticMarkup(<RecordCell field={f} value={value} />);
}

describe('RecordCell', () => {
  it('renders an em dash for null or missing', () => {
    expect(html(field({ type: 'text' }), null)).toContain('—');
    expect(html(field({ type: 'text' }), undefined)).toContain('—');
  });

  it('renders number/integer values as-is', () => {
    expect(html(field({ type: 'number' }), '9.99')).toContain('9.99');
    expect(html(field({ type: 'integer' }), 7)).toContain('7');
  });

  it('renders boolean true as a check and false as a dash', () => {
    expect(html(field({ type: 'boolean' }), true)).toContain('✓');
    expect(html(field({ type: 'boolean' }), false)).toContain('–');
  });

  it('formats a date without shifting the calendar day', () => {
    const out = html(field({ type: 'date' }), '2026-01-01');
    expect(out).toMatch(/Jan|1\/1|2026/);
  });

  it('resolves a select value to its choice label', () => {
    const f = field({
      type: 'select',
      options: {
        choices: [
          { value: 'lo', label: 'Low' },
          { value: 'hi', label: 'High' },
        ],
      },
    });
    expect(html(f, 'hi')).toContain('High');
  });

  it('falls back to the raw value for an orphaned choice', () => {
    const f = field({ type: 'select', options: { choices: [{ value: 'lo', label: 'Low' }] } });
    expect(html(f, 'removed')).toContain('removed');
  });

  it('joins multiselect labels with a comma', () => {
    const f = field({
      type: 'multiselect',
      options: {
        choices: [
          { value: 'a', label: 'Alpha' },
          { value: 'b', label: 'Beta' },
        ],
      },
    });
    expect(html(f, ['a', 'b'])).toContain('Alpha, Beta');
  });

  it('shows a relation as the first eight characters of its uuid', () => {
    const f = field({ type: 'relation', options: { target_type: 'author' } });
    const out = html(f, { type: 'author', uuid: '0123456789abcdef' });
    expect(out).toContain('01234567');
    expect(out).not.toContain('89abcdef');
  });

  it('falls back to a dash rather than crashing on a non-string uuid', () => {
    const f = field({ type: 'relation', options: { target_type: 'author' } });
    expect(html(f, { type: 'author', uuid: 12345 })).toContain('—');
  });

  it('renders an expanded relation as a link to the target title', () => {
    const f = field({ type: 'relation', options: { target_type: 'author' } });
    const value = { type: 'author', uuid: '0123456789abcdef' };
    const out = renderToStaticMarkup(
      <RecordCell
        field={f}
        value={value}
        expanded={[
          {
            type_key: 'author',
            uuid: '0123456789abcdef',
            display_title: 'Herbert',
            slug: 'herbert',
            status: 'published',
            dangling: false,
            restricted: false,
          },
        ]}
      />,
    );
    expect(out).toContain('Herbert');
    expect(out).toContain('href="/admin/records/author/0123456789abcdef"');
  });

  it('shows a muted marker for a dangling expanded relation, not the raw uuid', () => {
    const f = field({ type: 'relation', options: { target_type: 'author' } });
    const value = { type: 'author', uuid: '0123456789abcdef' };
    const out = renderToStaticMarkup(
      <RecordCell
        field={f}
        value={value}
        expanded={[
          {
            type_key: 'author',
            uuid: '0123456789abcdef',
            display_title: null,
            slug: null,
            status: null,
            dangling: true,
            restricted: false,
          },
        ]}
      />,
    );
    expect(out).toContain('Deleted');
    expect(out).toContain('01234567');
    expect(out).not.toContain('href=');
  });

  it('shows a muted marker for a restricted expanded relation, with no title or link', () => {
    const f = field({ type: 'relation', options: { target_type: 'author' } });
    const value = { type: 'author', uuid: '0123456789abcdef' };
    const out = renderToStaticMarkup(
      <RecordCell
        field={f}
        value={value}
        expanded={[
          {
            type_key: 'author',
            uuid: '0123456789abcdef',
            display_title: null,
            slug: null,
            status: null,
            dangling: false,
            restricted: true,
          },
        ]}
      />,
    );
    expect(out).toContain('Restricted');
    expect(out).not.toContain('href=');
    expect(out).not.toContain('01234567');
  });

  it('separates several expanded relations with a comma that hugs the chip', () => {
    const f = field({ type: 'relation', options: { target_type: 'author' } });
    const refs = [
      { type: 'author', uuid: 'aaaaaaaaaaaa' },
      { type: 'author', uuid: 'bbbbbbbbbbbb' },
    ];
    const out = renderToStaticMarkup(
      <RecordCell
        field={f}
        value={refs}
        expanded={refs.map((ref, index) => ({
          type_key: 'author',
          uuid: ref.uuid,
          display_title: index === 0 ? 'Herbert' : 'Le Guin',
          slug: null,
          status: 'published',
          dangling: false,
          restricted: false,
        }))}
      />,
    );
    // The separator trails its own chip's wrapper rather than being a flex
    // item of its own, which is what printed "Herbert , Le Guin" (UX-R17).
    const text = out.replace(/<[^>]+>/g, '');
    expect(text).toBe('Herbert,Le Guin');
  });

  it('truncates long text and keeps the full value in a title attribute', () => {
    const long = 'x'.repeat(80);
    const out = html(field({ type: 'text' }), long);
    expect(out).toContain(`title="${long}"`);
    expect(out).toContain('…');
  });
});
