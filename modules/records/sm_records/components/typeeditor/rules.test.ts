import { describe, expect, it } from 'vitest';

import { indexable, keyValid, normaliseOnToggle, uniqueAllowed } from './rules';

describe('indexable', () => {
  it('is true for every field type with an index table', () => {
    for (const type of [
      'text',
      'select',
      'multiselect',
      'email',
      'url',
      'number',
      'integer',
      'boolean',
      'date',
      'datetime',
      'relation',
    ]) {
      expect(indexable(type)).toBe(true);
    }
  });

  it('is false for longtext, json and media', () => {
    expect(indexable('longtext')).toBe(false);
    expect(indexable('json')).toBe(false);
    expect(indexable('media')).toBe(false);
  });
});

describe('uniqueAllowed', () => {
  it('is false for multiselect, longtext, json and media', () => {
    expect(uniqueAllowed({ type: 'multiselect' })).toBe(false);
    expect(uniqueAllowed({ type: 'longtext' })).toBe(false);
    expect(uniqueAllowed({ type: 'json' })).toBe(false);
    expect(uniqueAllowed({ type: 'media' })).toBe(false);
  });

  it('is false for a to-many relation, true for a to-one relation', () => {
    expect(uniqueAllowed({ type: 'relation', options: { many: true } })).toBe(false);
    expect(uniqueAllowed({ type: 'relation', options: { many: false } })).toBe(true);
    expect(uniqueAllowed({ type: 'relation' })).toBe(true);
  });

  it('is true for an ordinary scalar field', () => {
    expect(uniqueAllowed({ type: 'text' })).toBe(true);
    expect(uniqueAllowed({ type: 'number' })).toBe(true);
  });
});

describe('keyValid', () => {
  it('requires a non-empty key', () => {
    expect(keyValid('', [])).toBe('required');
  });

  it('reserves _orphaned', () => {
    expect(keyValid('_orphaned', [])).toBe('reserved');
  });

  it('rejects a key that does not match the pattern', () => {
    expect(keyValid('Bad-Key', [])).toBe('pattern');
    expect(keyValid('1abc', [])).toBe('pattern');
    expect(keyValid('has space', [])).toBe('pattern');
  });

  it('rejects a duplicate of an existing key', () => {
    expect(keyValid('title', ['title', 'price'])).toBe('duplicate');
  });

  it('accepts a well-formed, unique key', () => {
    expect(keyValid('release_date', ['title', 'price'])).toBeNull();
    expect(keyValid('a', [])).toBeNull();
  });
});

describe('normaliseOnToggle', () => {
  it('forces indexed and unique off for a non-indexable type', () => {
    const result = normaliseOnToggle({
      type: 'longtext',
      required: false,
      unique: true,
      indexed: true,
    });
    expect(result.indexed).toBe(false);
    expect(result.unique).toBe(false);
  });

  it('forces unique off for multiselect but leaves indexed alone', () => {
    const result = normaliseOnToggle({
      type: 'multiselect',
      required: false,
      unique: true,
      indexed: true,
    });
    expect(result.unique).toBe(false);
    expect(result.indexed).toBe(true);
  });

  it('forces unique off for a to-many relation', () => {
    const result = normaliseOnToggle({
      type: 'relation',
      options: { many: true },
      required: false,
      unique: true,
      indexed: true,
    });
    expect(result.unique).toBe(false);
    expect(result.indexed).toBe(true);
  });

  it('checking unique auto-checks indexed', () => {
    const result = normaliseOnToggle({
      type: 'text',
      required: false,
      unique: true,
      indexed: false,
    });
    expect(result.indexed).toBe(true);
    expect(result.unique).toBe(true);
  });

  it('is idempotent', () => {
    const once = normaliseOnToggle({
      type: 'text',
      required: false,
      unique: true,
      indexed: false,
    });
    const twice = normaliseOnToggle(once);
    expect(twice).toEqual(once);
  });

  it('leaves a well-formed non-unique field untouched', () => {
    const result = normaliseOnToggle({
      type: 'number',
      required: true,
      unique: false,
      indexed: true,
    });
    expect(result).toEqual({ type: 'number', required: true, unique: false, indexed: true });
  });
});
