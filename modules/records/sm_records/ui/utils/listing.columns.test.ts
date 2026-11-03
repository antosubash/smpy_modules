import { describe, expect, it } from 'vitest';

import {
  availableColumns,
  defaultColumnKeys,
  type ListUrlState,
  listParams,
  MAX_CHOSEN_COLUMNS,
  MAX_LIST_COLUMNS,
  resolveListColumns,
  sortHiddenBy,
} from './listing';
import type { FieldDef } from './types';

function field(key: string, overrides: Partial<FieldDef> = {}): FieldDef {
  return {
    key,
    type: 'text',
    label: key.toUpperCase(),
    required: false,
    unique: false,
    indexed: false,
    default: null,
    help: null,
    constraints: {},
    options: {},
    ...overrides,
  };
}

/** Six indexed fields `i1..i6`, two plain ones, `title` as the display field. */
const type = {
  display_field: 'title',
  fields: [
    field('title', { indexed: true }),
    ...[1, 2, 3, 4, 5, 6].map((n) => field(`i${n}`, { indexed: true })),
    field('body', { type: 'longtext' }),
    field('meta', { type: 'json' }),
  ],
};

const keys = (resolved: { columns: { key: string }[] }) => resolved.columns.map((c) => c.key);

describe('resolveListColumns — the default rule', () => {
  it('is the pre-chooser table: status, the first four indexed fields, then the dates', () => {
    const resolved = resolveListColumns({ type, showLocale: false, raw: null, saved: null });
    expect(resolved.source).toBe('default');
    expect(keys(resolved)).toEqual([
      'status',
      'i1',
      'i2',
      'i3',
      'i4',
      'position',
      'published_at',
      'updated_at',
    ]);
    expect(MAX_LIST_COLUMNS).toBe(4);
  });

  it('adds Language after Status only when the list shows language UI', () => {
    expect(defaultColumnKeys(type, true).slice(0, 2)).toEqual(['status', 'locale']);
    expect(defaultColumnKeys(type, false)).not.toContain('locale');
  });

  it('adds the first media field after the indexed fields, and only the first', () => {
    const withMedia = {
      ...type,
      fields: [field('photo', { type: 'media' }), ...type.fields, field('back', { type: 'media' })],
    };
    const resolved = resolveListColumns({
      type: withMedia,
      showLocale: false,
      raw: null,
      saved: null,
    });
    expect(keys(resolved)).toEqual([
      'status',
      'i1',
      'i2',
      'i3',
      'i4',
      'photo',
      'position',
      'published_at',
      'updated_at',
    ]);
    // Still an ordinary column: a view can leave it out.
    const chosen = resolveListColumns({
      type: withMedia,
      showLocale: false,
      raw: 'i1',
      saved: null,
    });
    expect(keys(chosen)).toEqual(['i1']);
  });
});

describe('resolveListColumns — ?columns= in the link', () => {
  it('renders exactly the named columns in the named order, indexed or not', () => {
    const resolved = resolveListColumns({
      type,
      showLocale: false,
      raw: 'body,i3,updated_at,i1',
      saved: null,
    });
    expect(resolved.source).toBe('url');
    expect(keys(resolved)).toEqual(['body', 'i3', 'updated_at', 'i1']);
    expect(resolved.unknown).toEqual([]);
  });

  it('drops unknown keys and reports them, never failing', () => {
    const resolved = resolveListColumns({
      type,
      showLocale: false,
      raw: 'i1,nope,status,gone',
      saved: null,
    });
    expect(keys(resolved)).toEqual(['i1', 'status']);
    expect(resolved.unknown).toEqual(['nope', 'gone']);
  });

  it('treats Language as unknown on a list that shows no language UI', () => {
    const resolved = resolveListColumns({ type, showLocale: false, raw: 'locale,i1', saved: null });
    expect(keys(resolved)).toEqual(['i1']);
    expect(resolved.unknown).toEqual(['locale']);
  });

  it('collapses duplicates and blank entries silently', () => {
    const resolved = resolveListColumns({
      type,
      showLocale: false,
      raw: 'i1,,i1, i2 ',
      saved: null,
    });
    expect(keys(resolved)).toEqual(['i1', 'i2']);
    expect(resolved.unknown).toEqual([]);
  });

  it(`cuts field columns past ${MAX_CHOSEN_COLUMNS}, keeping envelope toggles`, () => {
    const many = Array.from({ length: 12 }, (_, n) => field(`f${n}`));
    const resolved = resolveListColumns({
      type: { fields: many },
      showLocale: false,
      raw: [...many.map((f) => f.key), 'status'].join(','),
      saved: null,
    });
    expect(resolved.columns.filter((c) => c.kind === 'field')).toHaveLength(MAX_CHOSEN_COLUMNS);
    expect(keys(resolved)).toContain('status');
    expect(resolved.truncated).toBe(12 - MAX_CHOSEN_COLUMNS);
  });

  it('falls back to the saved choice when every key in the link is unknown', () => {
    const resolved = resolveListColumns({
      type,
      showLocale: false,
      raw: 'nope,gone',
      saved: ['i5'],
    });
    expect(resolved.source).toBe('saved');
    expect(keys(resolved)).toEqual(['i5']);
    expect(resolved.unknown).toEqual(['nope', 'gone']);
  });

  it('keeps an empty ?columns= as a real choice: Title only', () => {
    const resolved = resolveListColumns({ type, showLocale: false, raw: '', saved: ['i5'] });
    expect(resolved.source).toBe('url');
    expect(resolved.columns).toEqual([]);
  });
});

describe('resolveListColumns — precedence against the saved choice', () => {
  it('prefers the link over this browser’s saved choice', () => {
    const resolved = resolveListColumns({ type, showLocale: false, raw: 'i2', saved: ['i5'] });
    expect(resolved.source).toBe('url');
    expect(keys(resolved)).toEqual(['i2']);
  });

  it('applies the saved choice when the link has none, dropping stale keys quietly', () => {
    const resolved = resolveListColumns({
      type,
      showLocale: false,
      raw: null,
      saved: ['i6', 'renamed', 'body'],
    });
    expect(resolved.source).toBe('saved');
    expect(keys(resolved)).toEqual(['i6', 'body']);
    expect(resolved.unknown).toEqual([]);
  });

  it('uses the default when a saved choice no longer names anything', () => {
    const resolved = resolveListColumns({ type, showLocale: false, raw: null, saved: ['gone'] });
    expect(resolved.source).toBe('default');
  });
});

describe('availableColumns', () => {
  it('offers the envelope toggles first, then every declared field but the display field', () => {
    const all = availableColumns(type, false).map((c) => c.key);
    expect(all.slice(0, 4)).toEqual(['status', 'position', 'published_at', 'updated_at']);
    // Review 4, ux F6: Title already is the display field.
    expect(all).not.toContain('title');
    expect(all).toContain('meta');
    expect(availableColumns(type, true).map((c) => c.key)).toContain('locale');
  });

  it('drops the display field from a link or a saved choice without a notice', () => {
    const linked = resolveListColumns({ type, showLocale: false, raw: 'title,i2', saved: null });
    expect(keys(linked)).toEqual(['i2']);
    expect(linked.unknown).toEqual([]);
    // Naming only the display field is "Title only", not an unknown link.
    const only = resolveListColumns({ type, showLocale: false, raw: 'title', saved: null });
    expect([only.source, keys(only), only.unknown]).toEqual(['url', [], []]);
    const saved = resolveListColumns({
      type,
      showLocale: false,
      raw: null,
      saved: ['title', 'i3'],
    });
    expect([saved.source, keys(saved)]).toEqual(['saved', ['i3']]);
  });
});

describe('sortHiddenBy', () => {
  const available = availableColumns(type, false);
  const pick = (...k: string[]) => available.filter((c) => k.includes(c.key));

  it('keeps a sort whose column is still shown', () => {
    expect(sortHiddenBy({ field: 'i1', dir: 'asc' }, pick('i1', 'i2'), available)).toBe(false);
  });

  it('drops a sort whose column the change hides', () => {
    expect(sortHiddenBy({ field: 'i1', dir: 'desc' }, pick('i2'), available)).toBe(true);
    expect(sortHiddenBy({ field: 'updated_at', dir: 'asc' }, pick('i2'), available)).toBe(true);
  });

  it('never drops a sort on Title or on a column the chooser does not offer', () => {
    expect(sortHiddenBy({ field: 'display_title', dir: 'asc' }, [], available)).toBe(false);
    expect(sortHiddenBy({ field: 'created_at', dir: 'asc' }, [], available)).toBe(false);
    expect(sortHiddenBy(null, [], available)).toBe(false);
  });
});

describe('listParams — ?columns= rides along', () => {
  const lp = (...args: Parameters<typeof listParams>) => Object.fromEntries(listParams(...args));
  const offset: ListUrlState = {
    page: 3,
    after: null,
    filter: ['a:eq:x'],
    sort: ['i1'],
    trashed: false,
    pageSize: 25,
    columns: 'i1,status',
  };
  const cursor: ListUrlState = { ...offset, page: 1, after: 'CUR' };

  it('keeps it across a page, a cursor step, a filter, sort, trash or page-size change', () => {
    for (const next of [
      { page: 4 },
      { after: 'NEXT' },
      { filter: null },
      { sort: '-i2' },
      { trashed: true },
      { pageSize: 50 },
    ]) {
      expect(lp(cursor, next).columns).toBe('i1,status');
    }
  });

  it('changing it alone keeps the page or the cursor; only null drops it', () => {
    expect(lp(offset, { columns: 'i2' })).toMatchObject({ page: '3', columns: 'i2' });
    expect(lp(cursor, { columns: '' })).toMatchObject({ after: 'CUR', columns: '' });
    expect(lp(cursor, { columns: null })).toEqual({
      after: 'CUR',
      filter: 'a:eq:x',
      sort: 'i1',
    });
  });
});
