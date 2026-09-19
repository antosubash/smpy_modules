import { describe, expect, it } from 'vitest';

import { pendingEntries } from './reindexPending';

describe('pendingEntries', () => {
  it('returns an empty list for an empty map', () => {
    expect(pendingEntries({})).toEqual([]);
  });

  it('marks a single field key as not the whole type', () => {
    expect(pendingEntries({ price: '2026-09-19T10:00:00Z' })).toEqual([
      { key: 'price', since: '2026-09-19T10:00:00Z', wholeType: false },
    ]);
  });

  it('marks "*" as the whole-type sentinel', () => {
    expect(pendingEntries({ '*': '2026-09-19T10:00:00Z' })).toEqual([
      { key: '*', since: '2026-09-19T10:00:00Z', wholeType: true },
    ]);
  });

  it('preserves each entry’s own since timestamp', () => {
    const result = pendingEntries({ a: '2026-01-01T00:00:00Z', b: '2026-02-02T00:00:00Z' });
    expect(result.find((e) => e.key === 'a')?.since).toBe('2026-01-01T00:00:00Z');
    expect(result.find((e) => e.key === 'b')?.since).toBe('2026-02-02T00:00:00Z');
  });

  it('sorts field keys alphabetically', () => {
    const result = pendingEntries({ zebra: 't1', apple: 't2', mango: 't3' });
    expect(result.map((e) => e.key)).toEqual(['apple', 'mango', 'zebra']);
  });

  it('always places the whole-type entry first, ahead of every field key', () => {
    const result = pendingEntries({ zebra: 't1', '*': 't2', apple: 't3' });
    expect(result.map((e) => e.key)).toEqual(['*', 'apple', 'zebra']);
  });
});
