/**
 * Local prop/shape types for the schema editor. Kept out of
 * `utils/types.ts` deliberately — that file mirrors the wire contract every
 * page and component shares, and `TypeEditorProps` is this page's own Inertia
 * props, not a shape any other screen renders.
 */

import type { FieldDef, TypeRead } from '../../utils/types';

/** One entry of `props.target_types` — a candidate for `relation.options.
 *  target_type`, as `views.py::_editor_context` builds it. */
export type TargetType = { key: string; label: string };

/** Props for `Records/TypeEditor`, exactly as `endpoints/views.py` sends
 *  them for both `/types/new` (`type: null`) and `/types/{key}`. */
export type TypeEditorProps = {
  type: TypeRead | null;
  target_types: TargetType[];
  roles: string[];
};

/** A field row's local editing state. Identical in shape to the wire
 *  `FieldDef` — kept as its own alias so a future divergence (e.g. a
 *  UI-only draft flag) doesn't have to touch every import site. */
export type EditableField = FieldDef;

/** One choice of a `select`/`multiselect` field's `options.choices`. */
export type Choice = { value: string; label: string };

export const RELATION_ON_DELETE = ['restrict', 'set_null', 'cascade'] as const;
export type RelationOnDelete = (typeof RELATION_ON_DELETE)[number];

/** Mirrors `schema/fields.py::ON_DELETE_DEFAULT`. */
export const ON_DELETE_DEFAULT: RelationOnDelete = 'restrict';

/** The closed field-type set, in the order the "add field" select offers
 *  them — mirrors `sm_records.schema.types.FieldType`. */
export const FIELD_TYPES = [
  'text',
  'longtext',
  'number',
  'integer',
  'boolean',
  'date',
  'datetime',
  'select',
  'multiselect',
  'email',
  'url',
  'json',
  'media',
  'relation',
] as const;
export type FieldTypeName = (typeof FIELD_TYPES)[number];

/** Field types whose `constraints` the API accepts at all — mirrors
 *  `schema/fields.py::_ALLOWED_CONSTRAINTS`. */
export const TEXT_LIKE_TYPES: readonly FieldTypeName[] = ['text', 'longtext', 'email', 'url'];
export const NUMERIC_TYPES: readonly FieldTypeName[] = ['number', 'integer'];

/** Field types this screen renders a `default` input for. The rest
 *  (`multiselect`, `json`, `media`, `relation`) have no single-value input
 *  that maps cleanly onto their shape, so their `default` stays whatever it
 *  was and is not editable here. */
export const DEFAULT_EDITABLE_TYPES: readonly FieldTypeName[] = [
  'text',
  'longtext',
  'number',
  'integer',
  'boolean',
  'date',
  'datetime',
  'email',
  'url',
  'select',
];

/** Top-level `TypeUpdate`/`TypeCreate` keys — used to decide whether a 422
 *  `errors[].field` names the type itself or one of its `fields` (design
 *  doc's contract section: "field may be a top-level name ... or a field key
 *  from the schema validator"). A field definition could in principle reuse
 *  one of these names as its own `key`; when it does, the error is shown on
 *  the type-level input, which is the more common case in practice. */
/** The type-level form fields `TypeMetadataForm` owns, decoupled from the
 *  wire shape so the page can hold them as plain editable state before a
 *  save turns them back into a `TypeUpdate`/`TypeCreate` payload. */
export type TypeMetadataValues = {
  key: string;
  label: string;
  labelPlural: string;
  description: string;
  icon: string;
  isPublic: boolean;
  allowedRoles: string[];
  displayField: string;
  slugField: string;
};

export const TOP_LEVEL_ERROR_FIELDS = new Set([
  'key',
  'label',
  'label_plural',
  'description',
  'icon',
  'display_field',
  'slug_field',
  'is_public',
  'allowed_roles',
  'fields',
]);
