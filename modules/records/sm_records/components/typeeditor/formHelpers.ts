/**
 * Pure helpers for turning `TypeEditor`'s local draft state into API
 * payloads, and back. Extracted from the page so it stays well under the
 * 300-line cap once Phase 3's preview/reindex/revisions panels are wired in.
 */

import type { CreateTypePayload, UpdateTypeChanges } from '../../utils/api';
import type { TypeRead } from '../../utils/types';
import type { EditableField, TypeMetadataValues } from './types';

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
  if (JSON.stringify(fields) !== JSON.stringify(current.fields)) {
    changes.fields = fields;
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
  if (JSON.stringify(fields) !== JSON.stringify(current.fields)) return true;
  if (values.displayField !== (current.display_field ?? '')) return true;
  if (values.slugField !== (current.slug_field ?? '')) return true;
  return false;
}
