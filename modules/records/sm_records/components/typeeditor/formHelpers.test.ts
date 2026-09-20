import { describe, expect, it } from 'vitest';

import type { TypeRead } from '../../utils/types';
import { buildChanges, extraCreateFields, metadataFrom } from './formHelpers';

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
    expect(buildChanges(current, values, current.fields)).not.toHaveProperty('show_in_menu');
  });

  it('is sent when turned on', () => {
    const current = baseType({ show_in_menu: false });
    const values = { ...metadataFrom(current), showInMenu: true };
    expect(buildChanges(current, values, current.fields)).toMatchObject({ show_in_menu: true });
  });

  it('is sent when turned off', () => {
    const current = baseType({ show_in_menu: true });
    const values = { ...metadataFrom(current), showInMenu: false };
    expect(buildChanges(current, values, current.fields)).toMatchObject({ show_in_menu: false });
  });
});
