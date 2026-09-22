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
  /** The module's `public_route_prefix` setting (`views.py::_editor_context`)
   *  — `TypeMetadataForm` shows `{public_route_prefix}/{key}` when `is_public`
   *  is on, since the prefix is a DB-backed setting the browser has no other
   *  way to know (design §11). */
  public_route_prefix: string;
  /** Every content locale the module runs (design §4.4) — the "Translatable"
   *  toggle's help text names them, since that list is DB-backed configuration
   *  the browser has no other way to know. */
  content_locales: string[];
  /** Every record collection this host declared (Phase 5 §6.1). Empty on a
   *  host that declares none, and the new-type form then offers no control —
   *  which collections exist is decided by the host's Python and is not
   *  derivable from anything the browser holds. */
  collections: string[];
};

/** A field row's local editing state: the wire `FieldDef` plus `uid`, a
 *  client-only identity minted by `formHelpers.ts::newFieldUid` when the
 *  field is loaded or added. React keys the rows by it (UX review R10) and
 *  `stripUids` takes it back off before anything is sent, so the wire shape
 *  is unchanged.
 *
 *  `fromServer` is the other client-only flag, and it is what the
 *  immutable-key rule (§8.7) is actually about: this *row* came from the
 *  API, so its key is already written into records. Keyed by row identity
 *  and never by key value — a brand-new row that happens to spell an
 *  existing key is a typo to fix, not a saved field to protect (R1). */
export type EditableField = FieldDef & { uid: string; fromServer: boolean };

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
  translatable: boolean;
  /** `''` means the shared tables. Editable only while the type is new —
   *  `TypeMetadataForm` renders it as text once it exists (Phase 5 §6.2). */
  collection: string;
  /** Whether this type gets its own admin sidebar entry, next to the
   *  "Records" hub (per-type sidebar entries design contract). Off by
   *  default for a new type. */
  showInMenu: boolean;
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
  'translatable',
  'collection',
  'show_in_menu',
]);
