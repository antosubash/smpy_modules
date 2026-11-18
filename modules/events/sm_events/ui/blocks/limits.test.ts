import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import {
  CALENDARS_MAX,
  clampCount,
  oneOf,
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
