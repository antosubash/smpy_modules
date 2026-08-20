import { describe, expect, it } from 'vitest';

import { slugify } from './slugify';

/** The pattern pagebuilder's `PageCreate.slug` validates against. A slug that
 *  fails it is a 422 the author has no way to act on. */
const PAGE_SLUG_PATTERN = /^[a-z0-9][a-z0-9-]*$/;

describe('slugify — matching news/slugify.py', () => {
  it.each([
    ['Field Campaign in Estonia', 'field-campaign-in-estonia'],
    ['  leading and trailing  ', 'leading-and-trailing'],
    ['Ünïcodé folds', 'unicode-folds'],
    ['punctuation!!! -- everywhere', 'punctuation-everywhere'],
    ['--leading hyphens--', 'leading-hyphens'],
  ])('folds %j to %j', (title, expected) => {
    expect(slugify(title)).toBe(expected);
  });

  it.each(['???', '日本語', ''])('yields nothing for %j', (title) => {
    // Empty rather than invented: the server has the fallback, and two
    // implementations of it would be two things to keep in step.
    expect(slugify(title)).toBe('');
  });

  it.each([
    'Field Campaign in Estonia',
    '--leading hyphens--',
    'Ünïcodé folds',
    'a '.repeat(300),
    'x'.repeat(500),
  ])('produces something the page API accepts for %j', (title) => {
    const slug = slugify(title);

    expect(slug).not.toBe('');
    expect(slug.length).toBeLessThanOrEqual(200);
    expect(slug).toMatch(PAGE_SLUG_PATTERN);
  });
});
