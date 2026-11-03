import { describe, expect, it } from 'vitest';

import {
  allSelected,
  deselectAll,
  range,
  selectAll,
  someSelected,
  toggle,
  visible,
} from './selection';

const PAGE = ['a', 'b', 'c', 'd', 'e'];

describe('toggle', () => {
  it('adds what is not there and removes what is', () => {
    expect([...toggle(new Set(), 'a')]).toEqual(['a']);
    expect([...toggle(new Set(['a', 'b']), 'a')]).toEqual(['b']);
  });

  it('does not mutate the set it was given', () => {
    const before = new Set(['a']);
    toggle(before, 'b');
    expect([...before]).toEqual(['a']);
  });
});

describe('range — Shift+click', () => {
  it('adds every row between the anchor and the click, in either direction', () => {
    expect([...range(new Set(['b']), PAGE, 'b', 'd')].sort()).toEqual(['b', 'c', 'd']);
    expect([...range(new Set(['d']), PAGE, 'd', 'b')].sort()).toEqual(['b', 'c', 'd']);
  });

  it('never deselects: rows outside the range are left exactly as they were', () => {
    expect([...range(new Set(['a', 'e']), PAGE, 'b', 'c')].sort()).toEqual(['a', 'b', 'c', 'e']);
  });

  it('degrades to a plain toggle when there is no anchor yet', () => {
    expect([...range(new Set(), PAGE, null, 'c')]).toEqual(['c']);
  });

  it('degrades to a plain toggle when the anchor is no longer on the page', () => {
    // The list reloaded, or a filter moved the anchored row off this page:
    // there is no range left to mean anything, and inventing one would select
    // rows the operator never saw between their two clicks.
    expect([...range(new Set(['c']), PAGE, 'zz', 'c')]).toEqual([]);
  });
});

describe('select all, on this page only', () => {
  it('adds every row of the page and keeps what was selected elsewhere', () => {
    expect([...selectAll(new Set(['zz']), PAGE)].sort()).toEqual(['a', 'b', 'c', 'd', 'e', 'zz']);
  });

  it('deselecting removes only this page', () => {
    expect([...deselectAll(new Set([...PAGE, 'zz']), PAGE)]).toEqual(['zz']);
  });

  it('is not "all selected" on an empty page', () => {
    expect(allSelected(new Set(), [])).toBe(false);
    expect(allSelected(new Set(['a']), [])).toBe(false);
  });

  it('reports all, some and none apart', () => {
    expect(allSelected(new Set(PAGE), PAGE)).toBe(true);
    expect(someSelected(new Set(PAGE), PAGE)).toBe(false);
    expect(someSelected(new Set(['a']), PAGE)).toBe(true);
    expect(someSelected(new Set(), PAGE)).toBe(false);
  });
});

describe('what an action actually sends', () => {
  it('is the selection narrowed to this page, in page order', () => {
    expect(visible(new Set(['e', 'zz', 'a']), PAGE)).toEqual(['a', 'e']);
  });
});
