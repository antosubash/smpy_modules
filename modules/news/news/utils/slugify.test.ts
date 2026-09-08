import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import { slugify } from './slugify';

/** The shared rule, read rather than restated here.
 *
 * The table used to live in this file, and pagebuilder's copy of `slugify`
 * quietly disagreed with it on every letter NFKD leaves whole — the same
 * headline previewed as `strae-festival` on one admin screen and
 * `stra-e-festival` on the other. One file, read by the Python's test and by
 * both of the TypeScript ones, is what stops that recurring. */
const fixture = JSON.parse(
  readFileSync(
    fileURLToPath(new URL('../../../../tests/fixtures/slug_cases.json', import.meta.url)),
    'utf-8',
  ),
) as { max_length: number; cases: { input: string; expected: string }[] };

/** The pattern pagebuilder's `PageCreate.slug` validates against. A slug that
 *  fails it is a 422 the author has no way to act on. */
const PAGE_SLUG_PATTERN = /^[a-z0-9][a-z0-9-]*$/;

describe('slugify — matching news/slugify.py', () => {
  it.each(fixture.cases.map((c) => [c.input, c.expected] as const))(
    'folds %j to %j',
    (input, expected) => {
      // Empty stays empty rather than inventing a fallback: the server has
      // one, and two implementations of it would be two things to keep in
      // step.
      expect(slugify(input)).toBe(expected);
    },
  );

  it.each([
    'Field Campaign in Estonia',
    '--leading hyphens--',
    'Ünïcodé folds',
    // Long enough that the cut lands mid-separator, which is the case the
    // second trim exists for.
    `${'a'.repeat(199)} bc`,
    'a '.repeat(300),
    'x'.repeat(500),
  ])('produces something the page API accepts for %j', (title) => {
    const slug = slugify(title);

    expect(slug).not.toBe('');
    expect(slug.length).toBeLessThanOrEqual(fixture.max_length);
    expect(slug.endsWith('-')).toBe(false);
    expect(slug).toMatch(PAGE_SLUG_PATTERN);
  });
});
