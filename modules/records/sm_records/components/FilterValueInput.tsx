import { useT } from '@simple-module-py/i18n';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';

import type { FilterKind } from '../utils/filters';
import { localeLabel } from '../utils/locale';
import type { Translate } from '../utils/translate';
import type { FieldDef } from '../utils/types';
import {
  choicesOf,
  fieldConstraints,
  isoToLocalInput,
  localInputToIso,
  relationTarget,
} from '../utils/values';
import { RelationPicker } from './RelationPicker';

const VALUE_ID = 'records-filter-value';
const LABEL_ID = `${VALUE_ID}-label`;

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
      {selectFor(t, kind, value, locales, field, onChange) ??
        inputFor(kind, value, field, onChange)}
    </div>
  );
}

function selectFor(
  t: Translate,
  kind: FilterKind,
  value: string,
  locales: readonly string[],
  field: FieldDef | undefined,
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
  // U11: the table, the record editor and the type editor all present a
  // select/multiselect field by its choice label; this was the one place
  // that instead demanded the stored value through a free-text box with no
  // dropdown and no hint. `choicesOf` is the same reader the editor's own
  // `ChoiceFields` uses, so an empty choice list here means what it means
  // there — nothing configured yet — and falls through to the plain text
  // box below rather than rendering a `<select>` with no options.
  if (kind === 'select' && field) {
    const choices = choicesOf(field);
    if (choices.length === 0) return null;
    return (
      <NativeSelect id={VALUE_ID} value={value} onChange={(e) => onChange(e.target.value)}>
        {choices.map((choice) => (
          <NativeSelectOption key={choice.value} value={choice.value}>
            {choice.label}
          </NativeSelectOption>
        ))}
      </NativeSelect>
    );
  }
  return null;
}

/** A `constraints.min`/`.max` as an `<input min/max>` can take it — absent
 *  (or not a finite number) reads as "no bound", the same as the editor's
 *  own `checkRange` (utils/validation.ts) treats it. */
function bound(constraints: Record<string, unknown>, key: 'min' | 'max'): number | undefined {
  const raw = constraints[key];
  const num = typeof raw === 'number' ? raw : typeof raw === 'string' ? Number(raw) : Number.NaN;
  return Number.isFinite(num) ? num : undefined;
}

function inputFor(
  kind: FilterKind,
  value: string,
  field: FieldDef | undefined,
  onChange: (next: string) => void,
) {
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
  // U14: the same `type="number"` box the rest of this bar's typed controls
  // get, with the same bounds the editor's own `NumberField`/`IntegerField`
  // check (`constraints.min`/`.max` — utils/validation.ts's `checkRange`).
  // Unlike the editor, this *is* `type="number"` rather than text with an
  // `inputMode` hint: the value here only ever builds a `?filter=` query
  // string, so there is no five-decimal round-trip to a stored `Numeric`
  // column for a browser-normalised value to threaten.
  if ((kind === 'number' || kind === 'integer') && field) {
    const constraints = fieldConstraints(field);
    return (
      <Input
        id={VALUE_ID}
        type="number"
        inputMode={kind === 'integer' ? 'numeric' : 'decimal'}
        step={kind === 'integer' ? '1' : 'any'}
        min={bound(constraints, 'min')}
        max={bound(constraints, 'max')}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }
  return <Input id={VALUE_ID} value={value} onChange={(e) => onChange(e.target.value)} />;
}
