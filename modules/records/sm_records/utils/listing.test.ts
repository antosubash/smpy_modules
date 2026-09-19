import { describe, expect, it } from 'vitest';

import { buildSortParam, listColumns, nextSort, parseSort } from './listing';
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
