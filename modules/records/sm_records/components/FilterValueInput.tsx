import { useT } from '@simple-module-py/i18n';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';

import type { FilterKind } from '../utils/filters';
import { localeLabel } from '../utils/locale';
import type { FieldDef } from '../utils/types';
import { isoToLocalInput, localInputToIso, relationTarget } from '../utils/values';
import { RelationPicker } from './RelationPicker';

const VALUE_ID = 'records-filter-value';
const LABEL_ID = `${VALUE_ID}-label`;

// See `FilterBar.tsx` for why `t` is typed this loosely here.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

/**
 * The filter bar's value control, chosen by the kind of thing being
 * filtered (R8/M12) rather than always being a text box.
 *
 * The **URL grammar is unchanged** — every branch still produces the plain
 * string `?filter=field:op:value` carries, and that is the contract this
 * component is written around:
 *
 * - `boolean` → a select over `true`/`false`, the two `coerce_bool` spells
 *   canonically (it also takes `yes`/`on`/`1`, which no UI ever said).
 * - `date` → `type="date"`, whose value *is* `YYYY-MM-DD`.
 * - `datetime` → `type="datetime-local"`, converted through
 *   `localInputToIso` on the way out because `coerce_datetime` refuses a
 *   naive value rather than guessing a zone, and back through
 *   `isoToLocalInput` on the way in so a shared link repopulates the
 *   picker. `parseFilterParam` splits on the first two colons, so the
 *   colons in an ISO value are safe.
 * - `relation` → the editor's own `RelationPicker`, emitting the bare uuid
 *   `coerce_ref` expects in a filter. Pasting a 32-character uuid was the
 *   only way to filter a relation before this.
 */
export function FilterValueInput({
  kind,
  field,
  value,
  locales,
  onChange,
}: {
  kind: FilterKind;
  /** The schema field being filtered — absent for a fixed column. */
  field?: FieldDef;
  value: string;
  locales: readonly string[];
  onChange: (next: string) => void;
}) {
  const { t } = useT();
  const label = t('records.records.filter_value', { defaultValue: 'Value' });

  if (kind === 'relation' && field) {
    const target = relationTarget(field);
    return (
      <div className="grid gap-1.5">
        {/* The picker is a group of controls with no single input to point
            `htmlFor` at, so it takes an `aria-labelledby` (same treatment
            `FieldShell` gives it in the editor). */}
        <Label id={LABEL_ID}>{label}</Label>
        <RelationPicker
          field={field}
          value={value ? { type: target, uuid: value } : null}
          labelId={LABEL_ID}
          onChange={(next) => {
            const picked = next as { uuid?: string } | null;
            onChange(picked?.uuid ?? '');
          }}
        />
      </div>
    );
  }

  return (
    <div className="grid gap-1.5">
      <Label htmlFor={VALUE_ID}>{label}</Label>
      {selectFor(t, kind, value, locales, onChange) ?? inputFor(kind, value, onChange)}
    </div>
  );
}

function selectFor(
  t: Translate,
  kind: FilterKind,
  value: string,
  locales: readonly string[],
  onChange: (next: string) => void,
) {
  if (kind === 'status') {
    return (
      <NativeSelect id={VALUE_ID} value={value} onChange={(e) => onChange(e.target.value)}>
        <NativeSelectOption value="draft">
          {t('records.records.draft', { defaultValue: 'Draft' })}
        </NativeSelectOption>
        <NativeSelectOption value="published">
          {t('records.records.published', { defaultValue: 'Published' })}
        </NativeSelectOption>
      </NativeSelect>
    );
  }
  if (kind === 'locale') {
    return (
      <NativeSelect id={VALUE_ID} value={value} onChange={(e) => onChange(e.target.value)}>
        {locales.map((tag) => (
          <NativeSelectOption key={tag} value={tag}>
            {localeLabel(tag)}
          </NativeSelectOption>
        ))}
      </NativeSelect>
    );
  }
  if (kind === 'boolean') {
    return (
      <NativeSelect id={VALUE_ID} value={value} onChange={(e) => onChange(e.target.value)}>
        <NativeSelectOption value="true">
          {t('records.fields.boolean_yes', { defaultValue: 'Yes' })}
        </NativeSelectOption>
        <NativeSelectOption value="false">
          {t('records.fields.boolean_no', { defaultValue: 'No' })}
        </NativeSelectOption>
      </NativeSelect>
    );
  }
  return null;
}

function inputFor(kind: FilterKind, value: string, onChange: (next: string) => void) {
  if (kind === 'date') {
    return (
      <Input id={VALUE_ID} type="date" value={value} onChange={(e) => onChange(e.target.value)} />
    );
  }
  if (kind === 'datetime') {
    return (
      <Input
        id={VALUE_ID}
        type="datetime-local"
        step="1"
        value={isoToLocalInput(value)}
        onChange={(e) => onChange(e.target.value ? localInputToIso(e.target.value) : '')}
      />
    );
  }
  return <Input id={VALUE_ID} value={value} onChange={(e) => onChange(e.target.value)} />;
}
