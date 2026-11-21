import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import {
  CALENDARS_MAX,
  clampCount,
  countProblem,
  oneOf,
  selectionOf,
  slugsOf,
  UPCOMING_DEFAULT,
  UPCOMING_MAX,
} from './limits';

const CONSTANTS = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '../../core/constants/public.py',
);
const python = (name: string) =>
  Number(new RegExp(`^${name} = (\\d+)$`, 'm').exec(readFileSync(CONSTANTS, 'utf8'))?.[1]);

describe('limits', () => {
  it('mirror the server constants', () => {
    expect(UPCOMING_MAX).toBe(python('UPCOMING_BLOCK_MAX'));
    expect(UPCOMING_DEFAULT).toBe(python('UPCOMING_BLOCK_DEFAULT'));
    expect(CALENDARS_MAX).toBe(python('BLOCK_CALENDARS_MAX'));
  });

  it('clamps a count to a whole number in range', () => {
    expect(clampCount(4.5)).toBe(4);
    expect(clampCount(99)).toBe(UPCOMING_MAX);
    expect(clampCount(0)).toBe(1);
    expect(clampCount(-3)).toBe(1);
    expect(clampCount('x')).toBe(UPCOMING_DEFAULT);
    expect(clampCount(undefined)).toBe(UPCOMING_DEFAULT);
  });

  it('keeps an enum value or its fallback', () => {
    expect(oneOf('list', ['list', 'cards'], 'cards')).toBe('list');
    expect(oneOf('<script>', ['list', 'cards'], 'cards')).toBe('cards');
  });

  it('reads slugs defensively and bounds them', () => {
    expect(slugsOf([{ slug: 'a' }, { slug: ' b ' }, { slug: '' }, { slug: 'a' }, null, 7])).toEqual(
      ['a', 'b'],
    );
    expect(slugsOf('nope')).toEqual([]);
    expect(slugsOf(Array.from({ length: 30 }, (_, i) => ({ slug: `c${i}` })))).toHaveLength(
      CALENDARS_MAX,
    );
  });
});

describe('selectionOf: only an absent or empty selection means every calendar', () => {
  it('reads a well-formed selection', () => {
    expect(selectionOf([{ slug: 'a' }, { slug: ' b ' }])).toEqual({
      slugs: ['a', 'b'],
      bad: false,
    });
  });

  it('an absent or empty selection, or only blank rows, is no selection (every public calendar)', () => {
    for (const value of [undefined, null, [], [{ slug: '' }], [{ slug: '  ' }]]) {
      expect(selectionOf(value)).toEqual({ slugs: [], bad: false });
    }
  });

  it('a selection that cannot be read is bad: it means nothing, never everything', () => {
    for (const value of [
      'team',
      'a,b',
      7,
      {},
      { slug: 'a' },
      ['team'],
      [7],
      [null],
      [{}],
      [{ name: 'a' }],
      [{ slug: 7 }],
      [{ slug: 'a' }, null],
      [{ slug: 'a' }, 'b'],
    ]) {
      expect(selectionOf(value).bad, JSON.stringify(value)).toBe(true);
    }
  });

  it('more than the cap is bad too, and says nothing is dropped silently', () => {
    const many = Array.from({ length: CALENDARS_MAX + 1 }, (_, i) => ({ slug: `c${i}` }));
    expect(selectionOf(many).bad).toBe(true);
    expect(selectionOf(many.slice(0, CALENDARS_MAX)).bad).toBe(false);
  });
});

describe('countProblem: integers from 1 to the maximum, nothing clamped', () => {
  it('accepts a whole number in range', () => {
    for (const n of [1, 5, UPCOMING_MAX]) expect(countProblem(n)).toBeNull();
  });

  it('names what is wrong, for 0, a negative, too many, a fraction and not a number', () => {
    expect(countProblem(0)).toBe('range');
    expect(countProblem(-3)).toBe('range');
    expect(countProblem(99)).toBe('range');
    expect(countProblem(2.7)).toBe('integer');
    expect(countProblem(Number.NaN)).toBe('integer');
    expect(countProblem(undefined)).toBe('integer');
    expect(countProblem('5')).toBe('integer');
  });
});
