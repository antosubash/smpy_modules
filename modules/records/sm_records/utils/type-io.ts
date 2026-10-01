/**
 * Type-schema export and import (missing-UI M3).
 *
 * `GET /types/{key}/export` and `POST /types/import` have been in the API
 * (and under test) since Phase 5 with no frontend at all, which made moving
 * a schema between installs browser-impossible. The wire shapes here mirror
 * `contracts/io.py`'s `TypeExport`/`TypeImportRequest` exactly — this file
 * is the whole of what the browser needs to know about them.
 *
 * Export is a plain `<a href>`, not a `fetch`: the endpoint answers JSON the
 * operator wants as a file, and the browser's own download is the shortest
 * path to one. Import is a `POST` through `api.ts`'s `request`, so it gets
 * the module's session/offline handling and its `ApiError` shape — including
 * the 409s `useSchemaApply` already knows how to answer, because
 * `mode=update` routes through the very same `update_type` the schema editor
 * calls.
 */

import { request } from './api';
import type { FieldDef, TypeRead } from './types';

/** `contracts/io.py::TypeExport`. Deliberately `TypeCreate`-shaped:
 *  `record_count`, `version`, `schema_version` and `reindex_pending` are
 *  facts about one install's copy and do not travel. */
export type TypeDefinition = {
  key: string;
  label: string;
  label_plural?: string;
  description?: string | null;
  icon?: string | null;
  fields: FieldDef[];
  display_field?: string | null;
  slug_field?: string | null;
  is_public?: boolean;
  show_in_menu?: boolean;
  translatable?: boolean;
  allowed_roles?: string[];
};

/** `contracts/io.py::TypeImportRequest` — the definition plus the knobs the
 *  §8 pipeline needs. `force`/`orphaned` are what `useSchemaApply` merges on
 *  when a refused update is retried. */
export type TypeImportBody = TypeDefinition & {
  mode?: 'create' | 'update';
  expected_version?: number;
  force?: boolean;
  orphaned?: 'restore' | 'discard';
};

const BASE = '/api/records';

/** The download URL for one type's definition. */
export function typeExportUrl(key: string): string {
  return `${BASE}/types/${encodeURIComponent(key)}/export`;
}

/** The filename the browser saves it under — `<key>-schema.json`, matching
 *  the record export's `<key>-<date>.<ext>` habit of naming the type. */
export function typeExportFilename(key: string): string {
  return `${key}-schema.json`;
}

export type ParseFailure =
  | 'not_json'
  | 'not_object'
  | 'missing_key'
  | 'missing_label'
  | 'missing_fields';

export type ParsedDefinition =
  | { ok: true; definition: TypeDefinition }
  | { ok: false; reason: ParseFailure };

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * A picked file's text → a definition, or the reason it is not one.
 *
 * Checked here rather than posted hopefully: the server's refusal for a file
 * that is not a definition at all is a 422 about pydantic fields, which says
 * nothing to the person who picked the wrong file. Only the keys the import
 * actually reads are carried over, so a file with extra keys (a whole
 * `TypeRead`, version and record counts included) imports as the definition
 * inside it.
 */
export function parseTypeDefinition(text: string): ParsedDefinition {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ok: false, reason: 'not_json' };
  }
  if (!isObject(parsed)) return { ok: false, reason: 'not_object' };
  if (typeof parsed.key !== 'string' || parsed.key === '') {
    return { ok: false, reason: 'missing_key' };
  }
  if (typeof parsed.label !== 'string' || parsed.label === '') {
    return { ok: false, reason: 'missing_label' };
  }
  if (!Array.isArray(parsed.fields)) return { ok: false, reason: 'missing_fields' };
  const definition: TypeDefinition = {
    key: parsed.key,
    label: parsed.label,
    fields: parsed.fields as FieldDef[],
  };
  if (typeof parsed.label_plural === 'string') definition.label_plural = parsed.label_plural;
  if (typeof parsed.description === 'string') definition.description = parsed.description;
  if (typeof parsed.icon === 'string') definition.icon = parsed.icon;
  if (typeof parsed.display_field === 'string') definition.display_field = parsed.display_field;
  if (typeof parsed.slug_field === 'string') definition.slug_field = parsed.slug_field;
  if (typeof parsed.is_public === 'boolean') definition.is_public = parsed.is_public;
  if (typeof parsed.show_in_menu === 'boolean') definition.show_in_menu = parsed.show_in_menu;
  if (typeof parsed.translatable === 'boolean') definition.translatable = parsed.translatable;
  if (Array.isArray(parsed.allowed_roles)) {
    definition.allowed_roles = parsed.allowed_roles.filter(
      (role): role is string => typeof role === 'string',
    );
  }
  return { ok: true, definition };
}

/** `POST /types/import`. `mode=update` goes through the ordinary
 *  `update_type` path server-side, so a definition applied to a populated
 *  type is classified, dry-run and refused with exactly the report the
 *  schema editor's own save would get. */
export function importTypeDefinition(body: TypeImportBody): Promise<TypeRead> {
  return request('/types/import', { method: 'POST', body: JSON.stringify(body) });
}
