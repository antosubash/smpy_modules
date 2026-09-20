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
