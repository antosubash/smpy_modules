import { describe, expect, it } from 'vitest';

import {
  buildSortParam,
  exportSearchParams,
  filterErrorReasonKey,
  listColumns,
  nextSort,
  parseSort,
  parseTrashedParam,
} from './listing';
import type { FieldDef } from './types';

function field(overrides: Partial<FieldDef>): FieldDef {
  return {
    key: 'k',
    type: 'text',
    label: 'K',
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

describe('listColumns', () => {
  it('picks only indexed fields', () => {
    const fields = [
      field({ key: 'a', indexed: true }),
      field({ key: 'b', indexed: false }),
      field({ key: 'c', indexed: true }),
    ];
    expect(listColumns({ fields }).map((f) => f.key)).toEqual(['a', 'c']);
  });

  it('caps at four columns', () => {
    const fields = Array.from({ length: 6 }, (_, i) => field({ key: `f${i}`, indexed: true }));
    const columns = listColumns({ fields });
    expect(columns).toHaveLength(4);
    expect(columns.map((f) => f.key)).toEqual(['f0', 'f1', 'f2', 'f3']);
  });

  it('preserves the type schema order rather than sorting', () => {
    const fields = [field({ key: 'zebra', indexed: true }), field({ key: 'apple', indexed: true })];
    expect(listColumns({ fields }).map((f) => f.key)).toEqual(['zebra', 'apple']);
  });

  it('returns an empty array when nothing is indexed', () => {
    expect(listColumns({ fields: [field({ indexed: false })] })).toEqual([]);
  });
});

describe('nextSort', () => {
  it('starts a fresh column at asc', () => {
    expect(nextSort(null, 'status')).toEqual({ field: 'status', dir: 'asc' });
  });

  it('cycles the same column asc -> desc -> none', () => {
    const asc = nextSort(null, 'status');
    const desc = nextSort(asc, 'status');
    const none = nextSort(desc, 'status');
    expect(desc).toEqual({ field: 'status', dir: 'desc' });
    expect(none).toBeNull();
  });

  it('clicking a different column restarts it at asc, discarding the old one', () => {
    const onStatus = { field: 'status', dir: 'desc' as const };
    expect(nextSort(onStatus, 'display_title')).toEqual({ field: 'display_title', dir: 'asc' });
  });
});

describe('parseSort', () => {
  it('reads a plain field as ascending', () => {
    expect(parseSort('?sort=display_title')).toEqual({ field: 'display_title', dir: 'asc' });
  });

  it('reads a leading "-" as descending', () => {
    expect(parseSort('?sort=-updated_at')).toEqual({ field: 'updated_at', dir: 'desc' });
  });

  it('returns null when there is no sort param', () => {
    expect(parseSort('?filter=status:eq:draft')).toBeNull();
  });

  it('takes only the first sort when the query repeats it', () => {
    expect(parseSort('?sort=a&sort=-b')).toEqual({ field: 'a', dir: 'asc' });
  });
});

describe('buildSortParam', () => {
  it('renders ascending as the bare field name', () => {
    expect(buildSortParam({ field: 'position', dir: 'asc' })).toBe('position');
  });

  it('renders descending with a leading "-"', () => {
    expect(buildSortParam({ field: 'position', dir: 'desc' })).toBe('-position');
  });

  it('returns undefined for no sort', () => {
    expect(buildSortParam(null)).toBeUndefined();
  });

  it('round-trips through parseSort', () => {
    const sort = { field: 'published_at', dir: 'desc' as const };
    expect(parseSort(`?sort=${buildSortParam(sort)}`)).toEqual(sort);
  });
});

describe('filterErrorReasonKey', () => {
  it('passes every known QueryError reason through unchanged (F1)', () => {
    for (const reason of ['reindexing', 'unsupported_op', 'not_indexed', 'unknown', 'bad_value']) {
      expect(filterErrorReasonKey(reason)).toBe(reason);
    }
  });

  it('falls back to "generic" for a reason outside the closed set', () => {
    expect(filterErrorReasonKey('something_new')).toBe('generic');
  });

  it('falls back to "generic" for an absent reason', () => {
    expect(filterErrorReasonKey(undefined)).toBe('generic');
  });
});

describe('listColumns and the display field', () => {
  it('drops the column the Title column already prints', () => {
    const fields = [field({ key: 'name', indexed: true }), field({ key: 'city', indexed: true })];
    expect(listColumns({ fields, display_field: 'name' }).map((f) => f.key)).toEqual(['city']);
  });

  it('frees the dropped column for a field the cap would have cut', () => {
    const fields = Array.from({ length: 6 }, (_, i) => field({ key: `f${i}`, indexed: true }));
    expect(listColumns({ fields, display_field: 'f0' }).map((f) => f.key)).toEqual([
      'f1',
      'f2',
      'f3',
      'f4',
    ]);
  });

  it('keeps every column for a type with no display field', () => {
    const fields = [field({ key: 'a', indexed: true })];
    expect(listColumns({ fields, display_field: null }).map((f) => f.key)).toEqual(['a']);
  });
});

describe('parseTrashedParam', () => {
  // Matches pydantic's own `bool` query coercion (`deps.py::parse_trashed`'s
  // `Query(default=False)`) — the rough edge this closes is `?trashed=1`
  // reading as true on the server and false here, so the page rendered the
  // live empty state over rows the server had already sent it as the trash.
  it('reads every truthy spelling the server accepts, case-insensitively', () => {
    for (const raw of ['1', 'true', 'True', 'TRUE', 'yes', 'YES', 'on', 'y', 't']) {
      expect(parseTrashedParam(raw)).toBe(true);
    }
  });

  it('reads a falsy spelling, an absent param, and garbage as false', () => {
    for (const raw of ['0', 'false', 'no', 'off', 'n', 'f', null, '', 'garbage']) {
      expect(parseTrashedParam(raw)).toBe(false);
    }
  });
});

describe('exportSearchParams — polish: Export never carries a refused filter', () => {
  const query = 'filter=title%3Aeq%3Ax&sort=-updated_at&trashed=true&page=3';

  it('exports exactly what the screen is showing while the filter works', () => {
    expect(exportSearchParams(query, false)).toBe(query);
  });

  it('drops only the filter once the server has refused it', () => {
    const out = new URLSearchParams(exportSearchParams(query, true));
    expect(out.get('filter')).toBeNull();
    expect(out.get('sort')).toBe('-updated_at');
    expect(out.get('trashed')).toBe('true');
  });

  it('leaves an empty query alone', () => {
    expect(exportSearchParams('', true)).toBe('');
  });
});
