/**
 * The pure, `t()`-calling pieces of `FilterBar` — split out for the
 * 300-line cap once U11's select-choice support pushed the component over
 * it. Kept beside `FilterBar.tsx` rather than in `utils/filters.ts`: these
 * are the operator/fixed-column *labels* a person reads, not the
 * kind/op-set logic `filters.ts` and its own test file already own.
 */

import type { FilterKind } from '../utils/filters';
import { keys, type Translate } from '../utils/i18n';
import type { FieldDef, FilterOp } from '../utils/types';
import { choicesOf } from '../utils/values';

export type FilterableField = {
  key: string;
  label: string;
  ops: readonly FilterOp[];
  /** Which value control this field takes (R8/M12) — see `filterKind`. */
  kind: FilterKind;
  /** The schema field itself, for the kinds whose control needs more than
   *  the key (a `relation` needs its `options.target_type`). */
  def?: FieldDef;
};

/** Labels for the filter grammar's operators. Indexing the `filters.op`
 *  subtree with the `FilterOp` union only compiles while every operator has
 *  a catalogue entry. */
export function opLabel(t: Translate, op: FilterOp): string {
  return t(keys.records.filters.op[op]);
}

/** The fixed columns every type can filter on regardless of its schema
 *  (`sm_records.index.query.FIXED_COLUMNS`), narrowed to the one operator
 *  each is actually useful with here: `status` is a two-value enum, so
 *  anything but "is" is unhelpful noise, and `display_title` is free text,
 *  where "starts with" and "contains" are the two ops the fixed-column query
 *  layer accepts for it (`fixed_clause`: both need a text column, `gt`/`lt`
 *  need an ordered one — `display_title` is text and not ordered). `locale`
 *  only joins the list when the caller passes more than one — a single-locale
 *  install has nothing to filter between (design §4.4). */
export function fixedFilterFields(t: Translate, locales: string[]): FilterableField[] {
  const fields: FilterableField[] = [
    {
      key: 'display_title',
      // `starts_with` first: it is the one an index on
      // `(type_id, display_title, id)` can answer (F9), and `contains`
      // — `ILIKE '%term%'` — is a read of every row of the type by
      // construction.
      label: t(keys.records.records.display_title),
      ops: ['starts_with', 'contains'],
      kind: 'text',
    },
    {
      key: 'status',
      label: t(keys.records.records.status),
      ops: ['eq'],
      kind: 'status',
    },
  ];
  // `invalid`, and deliberately not `invalid_since`: the column is a
  // timestamp and the filter is the boolean view of it, so this reuses the
  // Yes/No select every `boolean` field gets (`sm_records.index._fixed`).
  // `eq` alone — the server refuses the ordered operators on it by name, and
  // `is_null` would be a second spelling of "No" in the same dropdown.
  fields.push({
    key: 'invalid',
    label: t(keys.records.records.invalid_filter),
    ops: ['eq'],
    kind: 'boolean',
  });
  if (locales.length > 1) {
    fields.push({
      key: 'locale',
      label: t(keys.records.records.locale),
      ops: ['eq'],
      kind: 'locale',
    });
  }
  return fields;
}

/** The stored `value`s of a field's choices (U11) — `[]` for anything that
 *  isn't a `select`/`multiselect`, or `normaliseFilterValue`'s `choices`
 *  parameter is simply unconsulted for another kind. */
export function choiceValues(field: FieldDef | undefined): string[] {
  return field ? choicesOf(field).map((choice) => choice.value) : [];
}
