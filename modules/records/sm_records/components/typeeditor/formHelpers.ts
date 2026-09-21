/**
 * Pure helpers for turning `TypeEditor`'s local draft state into API
 * payloads, and back. Extracted from the page so it stays well under the
 * 300-line cap once Phase 3's preview/reindex/revisions panels are wired in.
 */

import type { CreateTypePayload, UpdateTypeChanges } from '../../utils/api';
import type { FieldDef, TypeRead } from '../../utils/types';
import type { EditableField, TypeMetadataValues } from './types';

let uidCounter = 0;

/** A client-only identity for one editable field row (UX review R10). The
 *  wire has nothing stable to key a row by — `key` is empty until it is
 *  typed and editable until the first save — so React kept the DOM node at
 *  position *i* across a reorder and swapped the content through it, which
 *  left the focused "Move up" button pointing at the field that had just
 *  been displaced. Never sent: `stripUids` takes it back off. */
export function newFieldUid(): string {
  const webCrypto = globalThis.crypto;
  if (webCrypto && typeof webCrypto.randomUUID === 'function') return webCrypto.randomUUID();
  uidCounter += 1;
  return `field-${Date.now().toString(36)}-${uidCounter}`;
}

/** Give every field coming off the wire its own `uid`. */
export function withUids(fields: FieldDef[]): EditableField[] {
  return fields.map((field) => ({ ...field, uid: newFieldUid() }));
}

/**
 * Drop the client-only `uid` again — every payload and every comparison
 * against a server response goes through here, so the wire shape is exactly
 * what it was before R10 and a draft that only differs by `uid` never reads
 * as dirty. Written out key by key rather than as a rest-spread so the
 * `FieldDef` contract is the one thing this function can't drift from.
 */
export function stripUids(fields: EditableField[]): FieldDef[] {
  return fields.map((field) => ({
    key: field.key,
    type: field.type,
    label: field.label,
    required: field.required,
    unique: field.unique,
    indexed: field.indexed,
    default: field.default,
    help: field.help,
    constraints: field.constraints,
    options: field.options,
  }));
}

/** A type key derived from a label — the same shape `rules.ts::KEY_PATTERN`
 *  accepts, so the auto-filled value never needs correcting (R19). */
export function keyFromLabel(label: string): string {
  return label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^[^a-z]+/, '')
    .replace(/_+$/, '');
}

/** Singulars no suffix rule reaches. The guess is *withheld* for these
 *  rather than invented: "Persons" and "Childs" both read as a bug the
 *  operator then has to notice, while an untouched label is visibly still
 *  theirs to write. Matched on the last word, so "Contact Person" counts. */
const IRREGULAR_SINGULARS = new Set([
  'person',
  'child',
  'man',
  'woman',
  'foot',
  'tooth',
  'mouse',
  'goose',
]);

/**
 * A plural label guessed from the singular, English-style. Only ever an
 * opening offer: it stops the moment the operator types in the field
 * themselves (R19).
 *
 * A label that already ends in `s` is left exactly as typed — the old rule
 * suffixed everything ending in `s`/`x`/`z`/`ch`/`sh` with `es`, so the very
 * common case of naming a type by its plural ("Blog Posts") auto-filled
 * "Blog Postses" (UX verification, rough edge 4). Pluralising an already
 * plural word is the one mistake this function can make that looks like
 * gibberish rather than like a near miss.
 */
export function pluralFromLabel(label: string): string {
  const trimmed = label.trim();
  if (!trimmed) return '';
  const lower = trimmed.toLowerCase();
  if (lower.endsWith('s')) return trimmed;
  if (IRREGULAR_SINGULARS.has(lower.split(/\s+/).pop() ?? '')) return trimmed;
  if (/(x|z|ch|sh)$/.test(lower)) return `${trimmed}es`;
  if (/[^aeiou]y$/.test(lower)) return `${trimmed.slice(0, -1)}ies`;
  return `${trimmed}s`;
}

export function metadataFrom(type: TypeRead | null): TypeMetadataValues {
  return {
    key: type?.key ?? '',
    label: type?.label ?? '',
    labelPlural: type?.label_plural ?? '',
    description: type?.description ?? '',
    icon: type?.icon ?? '',
    isPublic: type?.is_public ?? false,
    allowedRoles: type?.allowed_roles ?? [],
    displayField: type?.display_field ?? '',
    slugField: type?.slug_field ?? '',
    translatable: type?.translatable ?? false,
    collection: type?.collection ?? '',
    showInMenu: type?.show_in_menu ?? false,
  };
}

export function sameStringSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const sa = [...a].sort();
  const sb = [...b].sort();
  return sa.every((v, i) => v === sb[i]);
}

/** The optional metadata the editor collects for a new type, in the shape
 *  `createType` sends. Absent keys are left to the server's defaults. */
export function extraCreateFields(values: TypeMetadataValues): Partial<CreateTypePayload> {
  const extra: Partial<CreateTypePayload> = {};
  if (values.description) extra.description = values.description;
  if (values.icon) extra.icon = values.icon;
  if (values.isPublic) extra.is_public = true;
  if (values.allowedRoles.length > 0) extra.allowed_roles = values.allowedRoles;
  if (values.displayField) extra.display_field = values.displayField;
  if (values.slugField) extra.slug_field = values.slugField;
  if (values.translatable) extra.translatable = true;
  // Omitted rather than sent as `null` when empty: `''` is this form's
  // spelling of "the shared tables", and the server's default is the same
  // thing said once (Phase 5 §6.2).
  if (values.collection) extra.collection = values.collection;
  if (values.showInMenu) extra.show_in_menu = true;
  return extra;
}

/** Only what changed, top-level, against `current` — `updateType` sends
 *  exactly these as `PUT`'s body alongside `expected_version` (design's
 *  contract: send only changed top-level keys). Phase 3 lifts the
 *  populated-type lock, so `fields`/`display_field`/`slug_field` are diffed
 *  unconditionally rather than only while a type is still empty. */
export function buildChanges(
  current: TypeRead,
  values: TypeMetadataValues,
  fields: EditableField[],
): UpdateTypeChanges {
  const changes: UpdateTypeChanges = {};
  if (values.label !== current.label) changes.label = values.label;
  if (values.labelPlural !== current.label_plural) changes.label_plural = values.labelPlural;
  if (values.description !== (current.description ?? '')) {
    changes.description = values.description || null;
  }
  if (values.icon !== (current.icon ?? '')) changes.icon = values.icon || null;
  if (values.isPublic !== current.is_public) changes.is_public = values.isPublic;
  if (!sameStringSet(values.allowedRoles, current.allowed_roles)) {
    changes.allowed_roles = values.allowedRoles;
  }
  if (values.displayField !== (current.display_field ?? '')) {
    changes.display_field = values.displayField || null;
  }
  if (values.slugField !== (current.slug_field ?? '')) {
    changes.slug_field = values.slugField || null;
  }
  if (values.translatable !== current.translatable) changes.translatable = values.translatable;
  if (values.showInMenu !== current.show_in_menu) changes.show_in_menu = values.showInMenu;
  const wireFields = stripUids(fields);
  if (JSON.stringify(wireFields) !== JSON.stringify(current.fields)) {
    changes.fields = wireFields;
  }
  return changes;
}

/** Whether the local draft (`fields`, `displayField`, `slugField`) differs
 *  from what the server last returned — the "Preview changes" button is only
 *  meaningful, and only enabled, once one of these has actually moved. */
export function schemaIsDirty(
  current: TypeRead | null,
  values: TypeMetadataValues,
  fields: EditableField[],
): boolean {
  if (!current) return false;
  if (JSON.stringify(stripUids(fields)) !== JSON.stringify(current.fields)) return true;
  if (values.displayField !== (current.display_field ?? '')) return true;
  if (values.slugField !== (current.slug_field ?? '')) return true;
  return false;
}

/**
 * Whether anything at all on this screen differs from what is saved —
 * `schemaIsDirty` widened to the type's metadata, and to a new type that has
 * been typed into (UX review R12c/R22b). Two things read it: the Save button,
 * which is disabled while it is false rather than answering a no-op write
 * with a green "Saved" toast, and `useUnsavedGuard`, which asks before a
 * navigation throws the draft away.
 *
 * `buildChanges` is the diff for an existing type — reusing it means a field
 * added to the editor is covered here the day it is added there, instead of
 * quietly falling out of both the guard and the button.
 */
export function typeIsDirty(
  current: TypeRead | null,
  values: TypeMetadataValues,
  fields: EditableField[],
): boolean {
  if (!current) {
    return fields.length > 0 || JSON.stringify(values) !== JSON.stringify(metadataFrom(null));
  }
  return Object.keys(buildChanges(current, values, fields)).length > 0;
}
