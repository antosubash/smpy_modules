import { describe, expect, it } from 'vitest';

import { fromValidationErrors } from './http';

/**
 * FastAPI answers a bad field with 422 and a *list* of Pydantic errors. The
 * old code stringified that list, so typing a space into a URL field produced
 * `[{"type":"string_pattern_mismatch","loc":["body","slug"],…}]` on screen.
 */

const PYDANTIC_SLUG_ERROR = [
  {
    type: 'string_pattern_mismatch',
    loc: ['body', 'slug'],
    msg: "String should match pattern '^[a-z0-9][a-z0-9-]*$'",
    input: 'Not A Slug',
  },
];

describe('fromValidationErrors', () => {
  it('names the field and says what is wrong', () => {
    expect(fromValidationErrors(PYDANTIC_SLUG_ERROR)).toBe(
      "slug: String should match pattern '^[a-z0-9][a-z0-9-]*$'",
    );
  });

  it('drops the "body" wrapper, which means nothing to the reader', () => {
    expect(fromValidationErrors(PYDANTIC_SLUG_ERROR)).not.toContain('body');
  });

  it('joins several field errors', () => {
    const both = [
      { loc: ['body', 'slug'], msg: 'is required' },
      { loc: ['body', 'title'], msg: 'is too long' },
    ];

    expect(fromValidationErrors(both)).toBe('slug: is required; title: is too long');
  });

  it('drops list indices from the path', () => {
    const nested = [{ loc: ['body', 'tags', 0], msg: 'is too long' }];

    expect(fromValidationErrors(nested)).toBe('tags: is too long');
  });

  it('falls back when an entry carries no message', () => {
    expect(fromValidationErrors([{ loc: ['body', 'slug'] }])).toBe('slug: is not valid');
  });

  it('returns null for anything that is not a validation list', () => {
    // The caller then uses the string detail or the status line instead.
    expect(fromValidationErrors('already in use')).toBeNull();
    expect(fromValidationErrors(undefined)).toBeNull();
    expect(fromValidationErrors([])).toBeNull();
    expect(fromValidationErrors({ detail: 'x' })).toBeNull();
  });
});
