import { describe, expect, it } from 'vitest';

import en from '../locales/en.json';
import { fromValidationErrors } from './request';
import { slugify } from './slugify';
import { isValidSlug, validationMessage } from './slugRule';

const SENTENCE = en.settings.slug_invalid;

/** FastAPI's 422 entry for `slug` failing `PageUpdate.slug`'s pattern. */
const PATTERN_MISMATCH = {
  type: 'string_pattern_mismatch',
  loc: ['body', 'slug'],
  msg: "String should match pattern '^[a-z0-9][a-z0-9-]*$'",
};

describe('isValidSlug', () => {
  it.each(['about', 'a', '2026-plans', 'a-b-c'])('accepts %s', (slug) => {
    expect(isValidSlug(slug)).toBe(true);
  });

  it.each(['', 'About', 'über', 'a b', '-lead', 'a_b', 'a/b'])('rejects %j', (slug) => {
    expect(isValidSlug(slug)).toBe(false);
  });

  it('accepts whatever slugify produces', () => {
    for (const title of ['Field notes', 'Étude №1', '2026: the plan']) {
      expect(isValidSlug(slugify(title))).toBe(true);
    }
  });
});

describe('validationMessage', () => {
  it('explains a slug pattern mismatch instead of quoting the regex', () => {
    expect(validationMessage(PATTERN_MISMATCH)).toBe(SENTENCE);
  });

  it('leaves other rejections of the slug to pydantic', () => {
    expect(validationMessage({ type: 'string_too_long', loc: ['body', 'slug'] })).toBeNull();
  });

  it('leaves a pattern mismatch on another field alone', () => {
    expect(
      validationMessage({ type: 'string_pattern_mismatch', loc: ['body', 'locale'] }),
    ).toBeNull();
  });
});

describe('fromValidationErrors with a slug mismatch', () => {
  it("falls back to pydantic's text if the error type is ever renamed", () => {
    const renamed = { ...PATTERN_MISMATCH, type: 'string_regex_mismatch' };

    expect(fromValidationErrors([renamed])).toBe(`slug: ${PATTERN_MISMATCH.msg}`);
  });

  it('shows the sentence, without the regex or a field prefix', () => {
    const message = fromValidationErrors([PATTERN_MISMATCH]);

    expect(message).toBe(SENTENCE);
    expect(message).not.toContain('pattern');
  });

  it('keeps the other entries as they were', () => {
    const message = fromValidationErrors([
      PATTERN_MISMATCH,
      { type: 'string_too_short', loc: ['body', 'title'], msg: 'too short' },
    ]);

    expect(message).toBe(`${SENTENCE}; title: too short`);
  });
});
