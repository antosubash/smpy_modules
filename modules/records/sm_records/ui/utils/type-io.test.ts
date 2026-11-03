import { describe, expect, it } from 'vitest';

import { parseTypeDefinition, typeExportFilename, typeExportUrl } from './type-io';

const DEFINITION = {
  key: 'book',
  label: 'Book',
  label_plural: 'Books',
  description: 'keep me',
  icon: 'database',
  fields: [{ key: 'title', type: 'text', label: 'Title', indexed: true }],
  display_field: 'title',
  slug_field: null,
  is_public: true,
  show_in_menu: false,
  translatable: true,
  allowed_roles: ['editor', 'manager'],
};

describe('typeExportUrl — M3', () => {
  it('points at the definition endpoint, key-encoded', () => {
    expect(typeExportUrl('book')).toBe('/api/records/types/book/export');
    expect(typeExportUrl('a b')).toBe('/api/records/types/a%20b/export');
    expect(typeExportFilename('book')).toBe('book-schema.json');
  });
});

describe('parseTypeDefinition — M3', () => {
  it('carries every key TypeExport ships', () => {
    const parsed = parseTypeDefinition(JSON.stringify(DEFINITION));
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.definition).toMatchObject({
      key: 'book',
      label: 'Book',
      label_plural: 'Books',
      description: 'keep me',
      icon: 'database',
      display_field: 'title',
      is_public: true,
      show_in_menu: false,
      translatable: true,
      allowed_roles: ['editor', 'manager'],
    });
    expect(parsed.definition.fields).toHaveLength(1);
  });

  it('keeps only the definition out of a whole TypeRead', () => {
    // An operator may well paste `GET /types/{key}`'s body; `version`,
    // `record_count` and friends are facts about that install's copy and
    // the import contract does not take them.
    const parsed = parseTypeDefinition(
      JSON.stringify({ ...DEFINITION, version: 7, record_count: 12, reindex_pending: {} }),
    );
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.definition).not.toHaveProperty('version');
    expect(parsed.definition).not.toHaveProperty('record_count');
  });

  it('says which way the file is wrong instead of posting it hopefully', () => {
    expect(parseTypeDefinition('not json at all')).toEqual({ ok: false, reason: 'not_json' });
    expect(parseTypeDefinition('[1, 2]')).toEqual({ ok: false, reason: 'not_object' });
    expect(parseTypeDefinition('{"label":"Book","fields":[]}')).toEqual({
      ok: false,
      reason: 'missing_key',
    });
    expect(parseTypeDefinition('{"key":"book","fields":[]}')).toEqual({
      ok: false,
      reason: 'missing_label',
    });
    expect(parseTypeDefinition('{"key":"book","label":"Book"}')).toEqual({
      ok: false,
      reason: 'missing_fields',
    });
  });

  it('accepts a definition with no fields yet, which is a real type', () => {
    const parsed = parseTypeDefinition('{"key":"book","label":"Book","fields":[]}');
    expect(parsed.ok).toBe(true);
  });
});
