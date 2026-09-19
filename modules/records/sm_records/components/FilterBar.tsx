import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { useState } from 'react';

import { opsForFieldType } from '../utils/filters';
import { FILTER_OPS, type FieldDef, type FilterOp } from '../utils/types';

/** Labels for the filter grammar's operators. A plain `t()` call per op
 *  (rather than a module-scope `Record<FilterOp, string>`) so the strings
 *  stay reachable by `make ci-check-untranslated` — a config object is
 *  exactly the blind spot that check can't see through. */
// `useT()`'s `t` is overloaded against a generated translation-key union;
// typing this parameter against it (rather than accepting any translator)
// either blows up TS with an "excessively deep" instantiation over the
// template-literal key, or fails to unify with the real `TFunction`'s
// overload set when called here.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

function opLabel(t: Translate, op: FilterOp): string {
  const defaults: Record<FilterOp, string> = {
    eq: 'is',
    ne: 'is not',
    contains: 'contains',
    gt: '>',
    gte: '>=',
    lt: '<',
    lte: '<=',
    in: 'is one of (comma-separated)',
    is_null: 'is empty',
  };
  return t(`records.filters.op.${op}`, { defaultValue: defaults[op] });
}

export type FilterValue = { field: string; op: FilterOp; value: string } | null;

type FilterableField = { key: string; label: string; ops: readonly FilterOp[] };

/** The two fixed columns every type can filter on regardless of its schema
 *  (`sm_records.index.query.FIXED_COLUMNS`), narrowed to the one operator
 *  each is actually useful with here: `status` is a two-value enum, so
 *  anything but "is" is unhelpful noise, and `display_title` is free text,
 *  where "contains" is the only op the fixed-column query layer accepts for
 *  it (`_fixed_clause`: `contains` needs a text column, `gt`/`lt` need an
 *  ordered one — `display_title` is neither). */
function fixedFilterFields(t: Translate): FilterableField[] {
  return [
    {
      key: 'display_title',
      label: t('records.records.display_title', { defaultValue: 'Title' }),
      ops: ['contains'],
    },
    {
      key: 'status',
      label: t('records.records.status', { defaultValue: 'Status' }),
      ops: ['eq'],
    },
  ];
}

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
}: {
  fields: FieldDef[];
  current: FilterValue;
  onApply: (field: string, op: FilterOp, value: string) => void;
  onClear: () => void;
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
    }));
  const filterable = [...indexed, ...fixedFilterFields(t)];
  const fieldByKey = new Map(filterable.map((f) => [f.key, f]));

  const initialField = current?.field ?? filterable[0]?.key ?? '';
  const initialOps = fieldByKey.get(initialField)?.ops ?? filterable[0]?.ops ?? FILTER_OPS;
  // A `current` filter parsed out of the URL might name an op the field
  // doesn't actually allow (a hand-edited link, or a field whose `indexed`
  // kind changed since); fall back to the field's first allowed op rather
  // than trusting it, the same way `selectField` resets `op` below (F5).
  const initialOp =
    current?.op && initialOps.includes(current.op) ? current.op : (initialOps[0] ?? 'eq');

  const [field, setField] = useState(initialField);
  const [op, setOp] = useState<FilterOp>(initialOp);
  const [value, setValue] = useState(current?.value ?? '');

  if (filterable.length === 0) return null;

  const allowedOps = fieldByKey.get(field)?.ops ?? FILTER_OPS;
  const needsValue = op !== 'is_null';
  const isStatus = field === 'status';

  const selectField = (nextField: string) => {
    setField(nextField);
    const nextOps = fieldByKey.get(nextField)?.ops ?? FILTER_OPS;
    if (!nextOps.includes(op)) setOp(nextOps[0] ?? 'eq');
    if (nextField === 'status' && value !== 'draft' && value !== 'published') setValue('draft');
  };

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border p-3">
      <div className="grid gap-1.5">
        <Label htmlFor="records-filter-field">
          {t('records.records.filter_field', { defaultValue: 'Field' })}
        </Label>
        <NativeSelect
          id="records-filter-field"
          value={field}
          onChange={(e) => selectField(e.target.value)}
        >
          {filterable.map((f) => (
            <NativeSelectOption key={f.key} value={f.key}>
              {f.label}
            </NativeSelectOption>
          ))}
        </NativeSelect>
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
      {needsValue && isStatus && (
        <div className="grid gap-1.5">
          <Label htmlFor="records-filter-value">
            {t('records.records.filter_value', { defaultValue: 'Value' })}
          </Label>
          <NativeSelect
            id="records-filter-value"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          >
            <NativeSelectOption value="draft">
              {t('records.records.draft', { defaultValue: 'Draft' })}
            </NativeSelectOption>
            <NativeSelectOption value="published">
              {t('records.records.published', { defaultValue: 'Published' })}
            </NativeSelectOption>
          </NativeSelect>
        </div>
      )}
      {needsValue && !isStatus && (
        <div className="grid gap-1.5">
          <Label htmlFor="records-filter-value">
            {t('records.records.filter_value', { defaultValue: 'Value' })}
          </Label>
          <Input
            id="records-filter-value"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </div>
      )}
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          disabled={!field}
          onClick={() => onApply(field, op, needsValue ? value : 'true')}
        >
          {t('records.records.filter_apply', { defaultValue: 'Apply' })}
        </Button>
        {current && (
          <Button type="button" size="sm" variant="outline" onClick={onClear}>
            {t('records.records.filter_clear', { defaultValue: 'Clear' })}
          </Button>
        )}
      </div>
    </div>
  );
}
