/**
 * Which filter operators the record list UI offers, per field `type`.
 *
 * Mirrors `sm_records.index._predicates._ALLOWED`, restated here keyed by
 * `FieldType` instead of `IndexKind` (this side only ever has the field's
 * declared `type`, and re-deriving `IndexKind` from `schema/types.py` just to
 * look it up again would be indirection for its own sake):
 *
 * - TEXT  (text, select, multiselect, email, url): eq, ne, in, contains,
 *   starts_with
 * - BOOL  (boolean):                                eq, ne
 * - NUMBER (number, integer), DATE, DATETIME:        eq, ne, in, gt, gte, lt, lte
 * - REF   (relation):                                eq, ne, in
 *
 * Offering an operator the server refuses is worse than not offering it:
 * `value_clause` 409s with `unsupported_op`, and — before that response was
 * surfaced (see `pages/RecordList.tsx`) — the list rendered exactly like an
 * empty result set, with nothing to say why.
 *
 * `is_null` is deliberately absent from every set here even though the UI
 * still offers it: `query._term` answers it without ever calling
 * `value_clause` (so it never touches `_ALLOWED`), which makes it valid for
 * every kind uniformly rather than a per-kind concern this map decides.
 */

import type { FilterOp } from './types';

const TEXT_OPS: readonly FilterOp[] = ['eq', 'ne', 'in', 'contains', 'starts_with'];
const BOOL_OPS: readonly FilterOp[] = ['eq', 'ne'];
const ORDERED_OPS: readonly FilterOp[] = ['eq', 'ne', 'in', 'gt', 'gte', 'lt', 'lte'];
const REF_OPS: readonly FilterOp[] = ['eq', 'ne', 'in'];

/** Keyed by the wire `FieldType` string (`schema/types.py`) rather than an
 *  imported enum: `utils/types.ts` deliberately keeps `FieldDef.type` a bare
 *  `string` (see its header), so every consumer of a field's `type` already
 *  treats it this way. */
const OPS_BY_FIELD_TYPE: Record<string, readonly FilterOp[]> = {
  text: TEXT_OPS,
  select: TEXT_OPS,
  multiselect: TEXT_OPS,
  email: TEXT_OPS,
  url: TEXT_OPS,
  boolean: BOOL_OPS,
  number: ORDERED_OPS,
  integer: ORDERED_OPS,
  date: ORDERED_OPS,
  datetime: ORDERED_OPS,
  relation: REF_OPS,
};

/**
 * The comparison ops a field's `type` allows, per `_ALLOWED` — never
 * `is_null`, which callers add themselves when it's relevant (see the module
 * docstring). Empty for a type that cannot be indexed at all (`longtext`,
 * `json`, `media`): the schema validator refuses `indexed: true` on those, so
 * this is a defensive default rather than something reachable through the
 * filter UI, which only ever calls this for a field that is indexed.
 */
export function opsForFieldType(type: string): readonly FilterOp[] {
  return OPS_BY_FIELD_TYPE[type] ?? [];
}

/**
 * Disambiguates filter-field labels that collide (UX-R5).
 *
 * A type's own `order_status` field labelled "Status" and the fixed record
 * `status` column are two different filters with one name, and the dropdown
 * gave the user no way to tell them apart — picking one was a coin flip.
 * Any label that occurs more than once gains its key in parentheses, the
 * same disambiguation `RecordTable` already applies to a column header's
 * accessible name; a label that occurs once is left exactly as authored.
 */
export function disambiguateLabels<T extends { key: string; label: string }>(fields: T[]): T[] {
  const seen = new Map<string, number>();
  for (const field of fields) seen.set(field.label, (seen.get(field.label) ?? 0) + 1);
  return fields.map((field) =>
    (seen.get(field.label) ?? 0) > 1 ? { ...field, label: `${field.label} (${field.key})` } : field,
  );
}

/**
 * Which *control* the filter bar should offer for a field, as opposed to
 * which operators it allows (R8/M12).
 *
 * `status` and `locale` are the two fixed columns that have a closed value
 * set of their own; the rest follow the field's declared `type`. Everything
 * this map does not name is free text, which is what the whole bar used to
 * be — a boolean meant typing `true` (the server's `coerce_bool` also takes
 * `yes`/`on`/`1`, which nothing in the UI said), a date meant typing
 * `YYYY-MM-DD` by hand, and a relation meant pasting a 32-character uuid.
 */
export type FilterKind =
  | 'status'
  | 'locale'
  | 'boolean'
  | 'date'
  | 'datetime'
  | 'relation'
  | 'select'
  | 'text';

const KIND_BY_FIELD_TYPE: Record<string, FilterKind> = {
  boolean: 'boolean',
  date: 'date',
  datetime: 'datetime',
  relation: 'relation',
  // U11: the table, the record editor and the type editor all show a
  // select/multiselect field by its choice *label* ("California"); the
  // filter used to be the one place that demanded the stored *value*
  // ("CA") through a free-text box with no hint — and a value the field
  // doesn't recognise (a typo, "banana") 0-results silently rather than
  // erroring, unlike every other kind's bad-value case.
  select: 'select',
  multiselect: 'select',
};

export function filterKind(key: string, fieldType?: string): FilterKind {
  if (key === 'status') return 'status';
  if (key === 'locale') return 'locale';
  if (!fieldType) return 'text';
  return KIND_BY_FIELD_TYPE[fieldType] ?? 'text';
}

/**
 * A value the chosen control can actually represent.
 *
 * Every closed-set control (`status`, `locale`, `boolean`) has to answer
 * this, for the same reason `FilterBar` re-checks the op it was handed: the
 * value may come from a hand-edited or stale URL, and a `<select>` whose
 * `value` matches no `<option>` displays the *first* option while state
 * holds something else — so Apply then re-submits the filter that just
 * failed (the R16 shape, one control down). Free-text kinds keep whatever
 * they were given.
 */
export function normaliseFilterValue(
  kind: FilterKind,
  value: string,
  locales: readonly string[],
  /** The field's stored choice values (U11) — only consulted for `kind ===
   *  'select'`, since that's the only kind whose closed set isn't fixed at
   *  build time. Empty means "no choices configured yet", which normalises
   *  to `''` the same way an empty `locales` does for `locale`. */
  choices: readonly string[] = [],
): string {
  if (kind === 'status') return value === 'published' ? 'published' : 'draft';
  if (kind === 'locale') return locales.includes(value) ? value : (locales[0] ?? '');
  if (kind === 'boolean') return value === 'false' ? 'false' : 'true';
  if (kind === 'select') return choices.includes(value) ? value : (choices[0] ?? '');
  return value;
}

/** The value a freshly chosen field starts on — a select has no empty state
 *  to leave it in, so it starts on its first option. */
export function defaultFilterValue(
  kind: FilterKind,
  locales: readonly string[],
  choices: readonly string[] = [],
): string {
  return normaliseFilterValue(kind, '', locales, choices);
}
