import { describe, expect, it } from 'vitest';
import type { OccurrencePage } from '../types';
import { filtersKey, RangeCache } from './cache';

const page = (n: number): OccurrencePage => ({ items: [], truncated: n % 2 === 1 });
const r = (start: string, end: string) => ({ start, end });
const padded = r('2026-02-22T00:00:00Z', '2026-04-19T00:00:00Z');
const inside = r('2026-03-01T00:00:00Z', '2026-04-12T00:00:00Z');
const f = { calendars: ['a'], categories: [], types: [], locale: 'en' };

describe('RangeCache', () => {
  it('hits for a visible range inside a padded one with the same filters', () => {
    const cache = new RangeCache();
    cache.put(padded, filtersKey(f), page(1));
    expect(cache.find(inside, filtersKey(f))).toEqual(page(1));
  });
  it('misses on different filters or an outside range', () => {
    const cache = new RangeCache();
    cache.put(padded, filtersKey(f), page(1));
    expect(cache.find(inside, filtersKey({ ...f, calendars: ['b'] }))).toBeUndefined();
    expect(cache.find(inside, filtersKey({ ...f, locale: 'de' }))).toBeUndefined();
    expect(
      cache.find(r('2026-04-01T00:00:00Z', '2026-05-30T00:00:00Z'), filtersKey(f)),
    ).toBeUndefined();
  });
  it('evicts the least recently used entry past the limit', () => {
    const cache = new RangeCache(8);
    const day = (n: number) =>
      r(
        `2026-01-${String(n).padStart(2, '0')}T00:00:00Z`,
        `2026-01-${String(n).padStart(2, '0')}T01:00:00Z`,
      );
    for (let n = 1; n <= 8; n += 1) cache.put(day(n), 'k', page(n));
    expect(cache.find(day(1), 'k')).toBeDefined(); // touch: 1 is now the newest
    cache.put(day(9), 'k', page(9));
    expect(cache.find(day(2), 'k')).toBeUndefined(); // the oldest untouched one went
    expect(cache.find(day(1), 'k')).toBeDefined();
    expect(cache.find(day(9), 'k')).toBeDefined();
  });
  it('clear empties it', () => {
    const cache = new RangeCache();
    cache.put(padded, 'k', page(1));
    cache.clear();
    expect(cache.find(inside, 'k')).toBeUndefined();
  });
});
