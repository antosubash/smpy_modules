import { describe, expect, it } from 'vitest';

import {
  displayFieldAllowed,
  indexable,
  indexedForced,
  keyValid,
  MAX_KEY_LEN,
  MAX_LABEL_LEN,
  normaliseOnToggle,
  RESERVED_FIELD_KEYS,
  slugFieldAllowed,
  uniqueAllowed,
} from './rules';

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

  it('rejects a key past MAX_KEY_LEN, which the API 422s (R3)', () => {
    // The user guide documents the cap; before R3 the editor accepted it
    // and the save came back 422 with the over-long key as `field`, which
    // `groupErrors` cannot attribute to any row input.
    expect(keyValid('a'.repeat(MAX_KEY_LEN + 1), [])).toBe('too_long');
    expect(keyValid('a'.repeat(MAX_KEY_LEN), [])).toBeNull();
  });

  it('accepts a well-formed, unique key', () => {
    expect(keyValid('release_date', ['title', 'price'])).toBeNull();
    expect(keyValid('a', [])).toBeNull();
  });
});

describe('length caps mirror the API (R3)', () => {
  it('states the two the server enforces — pinned by tests/test_reserved_keys_sync.py', () => {
    expect(MAX_KEY_LEN).toBe(64);
    expect(MAX_LABEL_LEN).toBe(200);
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

describe('reserved field keys', () => {
  // Mirrors `sm_records.index._fixed.RESERVED_FIELD_KEYS`, which derives itself
  // from `Record.__table__.columns` + `index.query.FIXED_COLUMNS`. A key from
  // that set is answered by the query layer from `records_record`, not from
  // the field, so the save is refused on both sides.
  it('refuses every column a record already has', () => {
    for (const key of [
      '_orphaned',
      'id',
      'uuid',
      'type_id',
      'data',
      'schema_version',
      'version',
      'status',
      'slug',
      'display_title',
      'position',
      'published_at',
      'created_at',
      'updated_at',
      'created_by',
      'updated_by',
      'is_deleted',
      'deleted_at',
    ]) {
      expect(RESERVED_FIELD_KEYS.has(key)).toBe(true);
      expect(keyValid(key, [])).toBe('reserved');
    }
  });

  it('still accepts an ordinary key', () => {
    expect(keyValid('order_status', [])).toBeNull();
    expect(keyValid('title', [])).toBeNull();
  });
});

describe('indexedForced', () => {
  it('is true for a relation, however it is declared', () => {
    expect(indexedForced({ type: 'relation', unique: false })).toBe(true);
    expect(indexedForced({ type: 'relation', options: { many: true } })).toBe(true);
  });

  it('is true for a unique field and false otherwise', () => {
    expect(indexedForced({ type: 'text', unique: true })).toBe(true);
    expect(indexedForced({ type: 'text', unique: false })).toBe(false);
  });
});

describe('normaliseOnToggle for a relation', () => {
  it('forces indexed on, so on_delete has index rows to read', () => {
    const result = normaliseOnToggle({
      type: 'relation',
      options: { many: false },
      required: false,
      unique: false,
      indexed: false,
    });
    expect(result.indexed).toBe(true);
  });

  it('forces it on for a to-many relation too, which can never be unique', () => {
    const result = normaliseOnToggle({
      type: 'relation',
      options: { many: true },
      required: false,
      unique: true,
      indexed: false,
    });
    expect(result).toMatchObject({ indexed: true, unique: false });
  });
});

describe('pointer field types', () => {
  it('allows only what display_title can stringify sensibly', () => {
    for (const type of ['text', 'select', 'email', 'url', 'integer', 'number', 'date', 'datetime'])
      expect(displayFieldAllowed(type)).toBe(true);
    for (const type of ['json', 'media', 'multiselect', 'relation', 'longtext', 'boolean'])
      expect(displayFieldAllowed(type)).toBe(false);
  });

  it('allows only free text as a slug field', () => {
    for (const type of ['text', 'select', 'email', 'url'])
      expect(slugFieldAllowed(type)).toBe(true);
    for (const type of ['integer', 'number', 'date', 'datetime', 'boolean', 'json', 'relation'])
      expect(slugFieldAllowed(type)).toBe(false);
  });
});
