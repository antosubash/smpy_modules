/**
 * Client-side mirrors of the field rules `sm_records.schema.fields` enforces
 * server-side (design §6.1). Pure and dependency-free on purpose: this is the
 * one module the schema editor's checkboxes and key input consult on every
 * keystroke, and it is what `rules.test.ts` exercises directly. Keep it in
 * lock-step with `schema/fields.py` / `schema/types.py` — it exists so the
 * user sees the same refusal here that a save would otherwise bounce back as
 * a 422, not so it can drift into a second source of truth.
 */

/** Mirrors `schema.types.INDEX_KIND`'s keys — the field types with an index
 *  table to land in. Absent: `longtext`, `json`, `media` (design §7.3). */
const INDEXABLE_TYPES = new Set([
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
]);

/** Mirrors `schema.types.NOT_UNIQUE`. A `relation` joins this set only when
 *  it is `many` — checked separately in `uniqueAllowed`. */
const NOT_UNIQUE_TYPES = new Set(['multiselect', 'longtext', 'json', 'media']);

/** A field's `key` may never be this — `sm_records.constants.ORPHANED_KEY`. */
export const ORPHANED_KEY = '_orphaned';

/** A type or field key: lowercase identifier, URL- and JSON-safe. Mirrors
 *  `sm_records.constants.TYPE_KEY_PATTERN`. */
export const KEY_PATTERN = /^[a-z][a-z0-9_]*$/;

/** Whether a field of this `type` can be `indexed` — and therefore ever
 *  `unique`, since `unique` has nothing to check against otherwise. */
export function indexable(type: string): boolean {
  return INDEXABLE_TYPES.has(type);
}

/** The minimal shape `uniqueAllowed` and `normaliseOnToggle` need from a
 *  field: its `type`, and — for a `relation` — whether it is `many`. */
export type FieldTypeAndOptions = {
  type: string;
  options?: { many?: boolean };
};

/** Whether `unique: true` can mean anything for this field: refused on
 *  `multiselect`/`longtext`/`json`/`media` (nothing to be unique over,
 *  design §6.1) and on a to-many `relation` (many rows share one field). */
export function uniqueAllowed(field: FieldTypeAndOptions): boolean {
  if (NOT_UNIQUE_TYPES.has(field.type)) return false;
  if (field.type === 'relation' && field.options?.many) return false;
  return true;
}

export type KeyError = 'required' | 'reserved' | 'pattern' | 'duplicate';

/** Validate a proposed field (or type) key against the rules
 *  `schema/fields.py::_validate_key` enforces. `existingKeys` should exclude
 *  the key's own current value when editing in place, or every key would
 *  collide with itself. */
export function keyValid(key: string, existingKeys: readonly string[]): KeyError | null {
  if (!key) return 'required';
  if (key === ORPHANED_KEY) return 'reserved';
  if (!KEY_PATTERN.test(key)) return 'pattern';
  if (existingKeys.includes(key)) return 'duplicate';
  return null;
}

export type FieldFlags = FieldTypeAndOptions & {
  required: boolean;
  unique: boolean;
  indexed: boolean;
};

/**
 * Re-derive `unique`/`indexed` after any change to a field's `type`,
 * `options.many`, or the checkboxes themselves, so the two always agree with
 * what the server would accept:
 *
 * - Not `indexable`: both `indexed` and `unique` are forced off (§7.2 — a
 *   field that cannot be indexed cannot be queried, let alone uniquely).
 * - Not `uniqueAllowed`: `unique` is forced off.
 * - `unique` implies `indexed` — the server *normalises* this rather than
 *   refusing it (§6.1's `_validate_flags`), so the UI does the same instead
 *   of bouncing a save the API would have accepted.
 *
 * Idempotent — safe to call after every relevant change without tracking
 * which one happened.
 */
export function normaliseOnToggle(flags: FieldFlags): FieldFlags {
  const next = { ...flags };
  if (!indexable(next.type)) {
    next.indexed = false;
    next.unique = false;
    return next;
  }
  if (!uniqueAllowed(next)) next.unique = false;
  if (next.unique) next.indexed = true;
  return next;
}
