import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { useState } from 'react';

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

/**
 * One filter term — a field, an operator, and a value — that navigates via a
 * deep link (`?filter=field:op:value`) rather than filtering client-side.
 * Only `indexed` fields are offered: the API rejects a filter on anything
 * else with a `409`, and the design doc makes `indexed` the single most
 * consequential choice on the type's schema for exactly this reason.
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
  const indexed = fields.filter((f) => f.indexed);
  const [field, setField] = useState(current?.field ?? indexed[0]?.key ?? '');
  const [op, setOp] = useState<FilterOp>(current?.op ?? 'eq');
  const [value, setValue] = useState(current?.value ?? '');

  if (indexed.length === 0) return null;

  const needsValue = op !== 'is_null';

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-lg border p-3">
      <div className="grid gap-1.5">
        <Label htmlFor="records-filter-field">
          {t('records.records.filter_field', { defaultValue: 'Field' })}
        </Label>
        <NativeSelect
          id="records-filter-field"
          value={field}
          onChange={(e) => setField(e.target.value)}
        >
          {indexed.map((f) => (
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
          {FILTER_OPS.map((candidate) => (
            <NativeSelectOption key={candidate} value={candidate}>
              {opLabel(t, candidate)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>
      {needsValue && (
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
