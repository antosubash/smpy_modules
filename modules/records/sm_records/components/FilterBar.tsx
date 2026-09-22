import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import type React from 'react';
import { useState } from 'react';

import {
  defaultFilterValue,
  disambiguateLabels,
  filterKind,
  normaliseFilterValue,
  opsForFieldType,
} from '../utils/filters';
import type { FilterValue } from '../utils/listing';
import { FILTER_OPS, type FieldDef, type FilterOp } from '../utils/types';
import { FilterValueInput } from './FilterValueInput';
import { choiceValues, type FilterableField, fixedFilterFields, opLabel } from './filterBarFields';

// The shape lives in `utils/listing.ts` beside the parser that produces it
// from the URL; re-exported here because every consumer of this component
// already imports it from this module.
export type { FilterValue };

/**
 * One filter term — a field, an operator, and a value — that navigates via a
 * deep link (`?filter=field:op:value`) rather than filtering client-side.
 * Besides the two fixed columns above, only `indexed` fields are offered:
 * the API rejects a filter on anything else with a `409`, and the design
 * doc makes `indexed` the single most consequential choice on the type's
 * schema for exactly this reason.
 *
 * Initializes from `current` (the filter parsed out of the URL) and never
 * re-syncs to it afterwards — the caller remounts with a fresh `key` when
 * the URL's filter changes from outside this component (Back/Forward, or
 * its own "Clear" button), which is the React-recommended way to reset
 * state from a prop instead of an effect that fights the user's typing.
 */
export function FilterBar({
  fields,
  current,
  onApply,
  onClear,
  locales = [],
}: {
  fields: FieldDef[];
  current: FilterValue;
  onApply: (field: string, op: FilterOp, value: string) => void;
  onClear: () => void;
  /** Every content locale the module runs — omit or pass a single-entry list
   *  for a type that isn't translatable or an install that only runs one. */
  locales?: string[];
}) {
  const { t } = useT();
  const indexed: FilterableField[] = fields
    .filter((f) => f.indexed)
    .map((f) => ({
      key: f.key,
      label: f.label,
      // `in` is grammar-valid for most kinds (`_ALLOWED`) but is never
      // offered here — see the comment on `buildFilterParam` in
      // `utils/api.ts` (F6): the wire format joins an `in` list on a bare
      // comma with no escape, so a value containing one would silently
      // split into two terms. `is_null` is appended unconditionally because
      // the index layer answers it without ever consulting `_ALLOWED`
      // (`query._term` short-circuits before `value_clause`), so unlike the
      // comparison operators it doesn't vary by kind.
      ops: [...opsForFieldType(f.type).filter((op) => op !== 'in'), 'is_null'],
      kind: filterKind(f.key, f.type),
      def: f,
    }));
  // A fixed column is dropped when a declared field already claims the key,
  // so the dropdown can never list one twice. Moot since those names became
  // reserved field keys (`typeeditor/rules.ts::RESERVED_FIELD_KEYS`), but a
  // type saved before that still carries such a field.
  const declared = new Set(indexed.map((f) => f.key));
  // `disambiguateLabels` last, over the merged list: a type's own
  // `order_status` field labelled "Status" and the fixed `status` column are
  // two filters under one name, and the dropdown offered no way to tell them
  // apart (UX-R5). Colliding labels — from either half of this list — gain
  // their key in parentheses.
  const filterable = disambiguateLabels([
    ...indexed,
    ...fixedFilterFields(t, locales).filter((f) => !declared.has(f.key)),
  ]);
  const fieldByKey = new Map(filterable.map((f) => [f.key, f]));

  const initialField = current?.field ?? filterable[0]?.key ?? '';
  const initialOps = fieldByKey.get(initialField)?.ops ?? filterable[0]?.ops ?? FILTER_OPS;
  // A `current` filter parsed out of the URL might name an op the field
  // doesn't actually allow (a hand-edited link, or a field whose `indexed`
  // kind changed since); fall back to the field's first allowed op rather
  // than trusting it, the same way `selectField` resets `op` below (F5).
  const initialOp =
    current?.op && initialOps.includes(current.op) ? current.op : (initialOps[0] ?? 'eq');

  // A `?filter=` naming a field this type no longer has — de-indexed, or
  // renamed, or simply a hand-edited link (R16). The select used to be
  // handed this key with no matching option, so the browser displayed the
  // *first* option while state still held the missing one, and Apply
  // re-submitted the filter that had just failed. It gets an option of its
  // own instead, saying what it is, and Apply is held until another field
  // is chosen.
  const unknownField = current && !fieldByKey.has(current.field) ? current.field : null;
  const initialActive = fieldByKey.get(initialField);
  const initialKind = initialActive?.kind ?? 'text';

  const [field, setField] = useState(initialField);
  const [op, setOp] = useState<FilterOp>(initialOp);
  // Normalised, for the same reason `initialOp` is: a closed-set control
  // handed a value it has no option for shows its first option while state
  // holds the other one.
  const [value, setValue] = useState(() =>
    normaliseFilterValue(
      initialKind,
      current?.value ?? '',
      locales,
      choiceValues(initialActive?.def),
    ),
  );

  if (filterable.length === 0) return null;

  const active = fieldByKey.get(field);
  const allowedOps = active?.ops ?? FILTER_OPS;
  const kind = active?.kind ?? 'text';
  const needsValue = op !== 'is_null';

  const selectField = (nextField: string) => {
    setField(nextField);
    const next = fieldByKey.get(nextField);
    const nextOps = next?.ops ?? FILTER_OPS;
    if (!nextOps.includes(op)) setOp(nextOps[0] ?? 'eq');
    const nextKind = next?.kind ?? 'text';
    // A value only survives a field change when the same control can still
    // show it — a date string in a boolean select, or a uuid pointing at
    // another type, cannot.
    const sameTarget = nextKind !== 'relation' || next?.def === active?.def;
    if (nextKind !== kind || !sameTarget) {
      setValue(defaultFilterValue(nextKind, locales, choiceValues(next?.def)));
    }
  };

  // A `<form>` and not a `<div>` (UX-R2): the value input is the most-typed
  // control on the busiest screen in the module, and without implicit
  // submission Enter did nothing at all — no request, no URL change, no
  // feedback. `onApply` navigates, so the submit is always prevented first.
  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!field) return;
    onApply(field, op, needsValue ? value : 'true');
  };

  return (
    <form
      className="flex flex-wrap items-end gap-3 rounded-lg border p-3"
      data-testid="records-filter-bar"
      onSubmit={submit}
    >
      <div className="grid gap-1.5">
        <Label htmlFor="records-filter-field">
          {t('records.records.filter_field', { defaultValue: 'Field' })}
        </Label>
        <NativeSelect
          id="records-filter-field"
          value={field}
          onChange={(e) => selectField(e.target.value)}
        >
          {unknownField && field === unknownField && (
            <NativeSelectOption value={unknownField}>
              {t('records.records.filter_unknown_field', {
                field: unknownField,
                defaultValue: '{field} (not filterable)',
              })}
            </NativeSelectOption>
          )}
          {filterable.map((f) => (
            <NativeSelectOption key={f.key} value={f.key}>
              {f.label}
            </NativeSelectOption>
          ))}
        </NativeSelect>
        {field === unknownField && (
          <p className="text-sm text-muted-foreground" data-testid="records-filter-unknown">
            {t('records.records.filter_unknown_help', {
              defaultValue: 'This type has no filterable field by that name. Pick another.',
            })}
          </p>
        )}
      </div>
      <div className="grid gap-1.5">
        <Label htmlFor="records-filter-op">
          {t('records.records.filter_op', { defaultValue: 'Condition' })}
        </Label>
        <NativeSelect
          id="records-filter-op"
          value={op}
          onChange={(e) => setOp(e.target.value as FilterOp)}
        >
          {allowedOps.map((candidate) => (
            <NativeSelectOption key={candidate} value={candidate}>
              {opLabel(t, candidate)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>
      {needsValue && (
        <FilterValueInput
          kind={kind}
          field={active?.def}
          value={value}
          locales={locales}
          onChange={setValue}
        />
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!field || field === unknownField}>
          {t('records.records.filter_apply', { defaultValue: 'Apply' })}
        </Button>
        {current && (
          <Button type="button" size="sm" variant="outline" onClick={onClear}>
            {t('records.records.filter_clear', { defaultValue: 'Clear' })}
          </Button>
        )}
      </div>
    </form>
  );
}
