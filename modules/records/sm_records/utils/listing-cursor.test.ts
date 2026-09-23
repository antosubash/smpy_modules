import { describe, expect, it } from 'vitest';

import { exportUrl } from './io';
import {
  filterErrorMessage,
  isCursorRefusal,
  type ListUrlState,
  listParams,
  listStatus,
} from './listing';

// Echoes the key and the interpolation values, so a test can tell which
// sentence was chosen without a catalog.
const t = (key: string, opts: Record<string, unknown> = {}) =>
  `${key}${opts.count === undefined ? '' : `#${opts.count}`}`;

const offset: ListUrlState = {
  page: 3,
  after: null,
  filter: 'name:eq:x',
  sort: '-name',
  trashed: false,
  pageSize: 25,
};
const cursor: ListUrlState = { ...offset, page: 1, after: 'CURSOR' };

describe('listParams — the list URL, offset and cursor', () => {
  it('continues by cursor with `after` and no `page`, keeping filter and sort', () => {
    expect(listParams(offset, { after: 'NEXT' })).toEqual({
      after: 'NEXT',
      filter: 'name:eq:x',
      sort: '-name',
    });
  });

  it('never writes page and after together — the server refuses the pair', () => {
    const params = listParams(offset, { page: 4, after: 'NEXT' });
    expect(params.after).toBe('NEXT');
    expect(params.page).toBeUndefined();
  });

  it('keeps the cursor when nothing about the order changes', () => {
    expect(listParams(cursor, {})).toMatchObject({ after: 'CURSOR' });
  });

  it('drops the cursor for a numbered page — "First page" is page 1, no params', () => {
    expect(listParams(cursor, { page: 1 })).toEqual({ filter: 'name:eq:x', sort: '-name' });
    expect(listParams(cursor, { page: 2 })).toMatchObject({ page: '2' });
    expect(listParams(cursor, { page: 2 }).after).toBeUndefined();
  });

  it.each([
    ['sort', { sort: 'name' }],
    ['clearing the sort', { sort: null }],
    ['filter', { filter: 'locale:eq:de' }],
    ['clearing the filter', { filter: null }],
    ['trash toggle', { trashed: true }],
    ['page size', { pageSize: 50 }],
  ] as const)('a %s change drops the cursor and lands on page 1', (_, change) => {
    const params = listParams(cursor, change);
    expect(params.after).toBeUndefined();
    expect(params.page).toBeUndefined();
  });

  it('a reorder from a numbered page lands on page 1 too', () => {
    expect(listParams(offset, { sort: 'name' }).page).toBeUndefined();
  });

  it('writes page_size only when it differs from the default', () => {
    expect(listParams(offset, { pageSize: 25 }).page_size).toBeUndefined();
    expect(listParams(cursor, {}).page_size).toBeUndefined();
    expect(listParams({ ...cursor, pageSize: 100 }, {})).toMatchObject({
      after: 'CURSOR',
      page_size: '100',
    });
  });

  it('carries trashed on a cursor step, so the trash pages past the cap too', () => {
    expect(listParams({ ...offset, trashed: true }, { after: 'NEXT' })).toMatchObject({
      after: 'NEXT',
      trashed: 'true',
    });
  });
});

describe('exportUrl — an export is the whole set, never "from this row on"', () => {
  it('drops after and page and keeps filter/sort/trashed', () => {
    const url = new URL(
      exportUrl('book', 'csv', 'after=CURSOR&page=2&filter=a%3Aeq%3Ab&sort=-a&trashed=true'),
      'http://x',
    );
    expect(url.searchParams.get('after')).toBeNull();
    expect(url.searchParams.get('page')).toBeNull();
    expect(url.searchParams.get('filter')).toBe('a:eq:b');
    expect(url.searchParams.get('sort')).toBe('-a');
    expect(url.searchParams.get('trashed')).toBe('true');
  });
});

describe('the cursor refusals', () => {
  it('are told apart from filter refusals', () => {
    expect(isCursorRefusal('bad_cursor')).toBe(true);
    expect(isCursorRefusal('page_and_after')).toBe(true);
    for (const reason of ['reindexing', 'unknown', 'malformed', undefined]) {
      expect(isCursorRefusal(reason)).toBe(false);
    }
  });

  it('each have their own sentence, not the generic filter one', () => {
    expect(filterErrorMessage(t, 'bad_cursor')).toBe('records.list.filter_error.bad_cursor');
    expect(filterErrorMessage(t, 'page_and_after')).toBe(
      'records.list.filter_error.page_and_after',
    );
  });
});

describe('listStatus on a cursor page', () => {
  it('announces the count and no page number', () => {
    expect(listStatus(t, { count: 25, page: null, pages: 2, capped: true })).toBe(
      'records.records.list_status_cursor#25',
    );
  });

  it('is unchanged on a numbered page', () => {
    expect(listStatus(t, { count: 25, page: 2, pages: 2, capped: true })).toBe(
      'records.records.list_status_uncounted#25',
    );
  });
});
