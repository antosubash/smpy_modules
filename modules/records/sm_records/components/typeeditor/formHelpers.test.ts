import { describe, expect, it } from 'vitest';

import type { TypeRead } from '../../utils/types';
import {
  buildChanges,
  extraCreateFields,
  keyFromLabel,
  metadataFrom,
  pluralFromLabel,
  stripUids,
  typeIsDirty,
  withUids,
} from './formHelpers';

/** A minimal but complete `TypeRead`, so `buildChanges` (which reads every
 *  field off `current`) has something real to diff against. */
function baseType(overrides: Partial<TypeRead> = {}): TypeRead {
  return {
    key: 'widgets',
    label: 'Widget',
    label_plural: 'Widgets',
    description: null,
    icon: null,
    fields: [],
    schema_version: 1,
    version: 1,
    display_field: null,
    slug_field: null,
    is_public: false,
    allowed_roles: [],
    collection: null,
    record_count: 0,
    trashed_record_count: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: null,
    reindex_pending: {},
    translatable: false,
    show_in_menu: false,
    ...overrides,
  };
}

describe('metadataFrom — show_in_menu', () => {
  it('defaults to off for a new type (no type loaded)', () => {
    expect(metadataFrom(null).showInMenu).toBe(false);
  });

  it('carries an existing type’s show_in_menu into the draft', () => {
    expect(metadataFrom(baseType({ show_in_menu: true })).showInMenu).toBe(true);
    expect(metadataFrom(baseType({ show_in_menu: false })).showInMenu).toBe(false);
  });
});

describe('extraCreateFields — show_in_menu', () => {
  it('omits show_in_menu when off, matching the server default', () => {
    const values = metadataFrom(null);
    expect(extraCreateFields(values)).not.toHaveProperty('show_in_menu');
  });

  it('sends show_in_menu: true when the switch was turned on', () => {
    const values = { ...metadataFrom(null), showInMenu: true };
    expect(extraCreateFields(values)).toMatchObject({ show_in_menu: true });
  });
});

describe('buildChanges — show_in_menu', () => {
  it('is absent when unchanged', () => {
    const current = baseType({ show_in_menu: true });
    const values = metadataFrom(current);
    expect(buildChanges(current, values, withUids(current.fields))).not.toHaveProperty(
      'show_in_menu',
    );
  });

  it('is sent when turned on', () => {
    const current = baseType({ show_in_menu: false });
    const values = { ...metadataFrom(current), showInMenu: true };
    expect(buildChanges(current, values, withUids(current.fields))).toMatchObject({
      show_in_menu: true,
    });
  });

  it('is sent when turned off', () => {
    const current = baseType({ show_in_menu: true });
    const values = { ...metadataFrom(current), showInMenu: false };
    expect(buildChanges(current, values, withUids(current.fields))).toMatchObject({
      show_in_menu: false,
    });
  });
});

/** One complete `FieldDef`, so `stripUids` has every wire key to carry. */
function field(key: string) {
  return {
    key,
    type: 'text',
    label: key,
    required: false,
    unique: false,
    indexed: false,
    default: null,
    help: null,
    constraints: {},
    options: {},
  };
}

describe('withUids / stripUids — R10 keeps the wire shape', () => {
  it('gives every field its own uid', () => {
    const [a, b] = withUids([field('one'), field('two')]);
    expect(a.uid).toBeTruthy();
    expect(b.uid).toBeTruthy();
    expect(a.uid).not.toBe(b.uid);
  });

  it('round-trips back to exactly the wire shape', () => {
    const wire = [field('one'), field('two')];
    expect(stripUids(withUids(wire))).toEqual(wire);
    expect(JSON.stringify(stripUids(withUids(wire)))).toBe(JSON.stringify(wire));
  });

  it('never leaves a uid in a payload', () => {
    const current = baseType({ fields: [field('one')] });
    const values = metadataFrom(current);
    const moved = withUids([field('two'), field('one')]);
    const changes = buildChanges(current, values, moved);
    expect(JSON.stringify(changes.fields)).not.toContain('uid');
  });

  it('does not read as dirty just because the draft carries uids', () => {
    const current = baseType({ fields: [field('one')] });
    expect(typeIsDirty(current, metadataFrom(current), withUids(current.fields))).toBe(false);
  });
});

describe('typeIsDirty — R22b', () => {
  it('is false for an untouched existing type', () => {
    const current = baseType();
    expect(typeIsDirty(current, metadataFrom(current), [])).toBe(false);
  });

  it('notices a metadata-only edit, which schemaIsDirty does not', () => {
    const current = baseType();
    const values = { ...metadataFrom(current), description: 'new' };
    expect(typeIsDirty(current, values, [])).toBe(true);
  });

  it('is false for an untouched new form and true once anything is typed', () => {
    expect(typeIsDirty(null, metadataFrom(null), [])).toBe(false);
    expect(typeIsDirty(null, { ...metadataFrom(null), label: 'W' }, [])).toBe(true);
    expect(typeIsDirty(null, metadataFrom(null), withUids([field('one')]))).toBe(true);
  });
});

describe('keyFromLabel / pluralFromLabel — R19', () => {
  it('derives a key the server would accept', () => {
    expect(keyFromLabel('Blog Posts')).toBe('blog_posts');
    expect(keyFromLabel('  Order #1  ')).toBe('order_1');
    expect(keyFromLabel('123 Go')).toBe('go');
    expect(keyFromLabel('')).toBe('');
  });

  it('guesses an English plural', () => {
    expect(pluralFromLabel('Widget')).toBe('Widgets');
    expect(pluralFromLabel('Box')).toBe('Boxes');
    expect(pluralFromLabel('Category')).toBe('Categories');
    expect(pluralFromLabel('')).toBe('');
  });
});
