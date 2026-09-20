import { useT } from '@simple-module-py/i18n';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';

import { isoToLocalInput, localInputToIso } from '../../utils/values';
import { type Choice, DEFAULT_EDITABLE_TYPES } from './types';

const NULLABLE = '__no_default__';

/**
 * A field's `default`, rendered with one plain input per type. Only the
 * types in `DEFAULT_EDITABLE_TYPES` get one here — `multiselect`, `json`,
 * `media` and `relation` have no single-value shape that maps cleanly onto
 * one input, so their `default` (if any) is left as whatever it already was
 * rather than guessed at with a textarea.
 */
export function DefaultInput({
  index,
  type,
  value,
  choices,
  onChange,
  disabled = false,
}: {
  /** The row's position in the field list — see `FieldOptions`'s own
   *  `index` doc comment (L5): deriving this input's `id` from `field.key`
   *  collided across rows sharing an empty or duplicate key. */
  index: number;
  type: string;
  value: unknown;
  choices: Choice[];
  onChange: (next: unknown) => void;
  disabled?: boolean;
}) {
  const { t } = useT();
  const id = `field-row-${index}-default`;
  const label = t('records.type_editor.default_label', { defaultValue: 'Default value' });

  if (!(DEFAULT_EDITABLE_TYPES as readonly string[]).includes(type)) return null;

  if (type === 'boolean' || type === 'select') {
    const noDefault = t('records.type_editor.no_default', { defaultValue: 'No default' });
    const current = value === null || value === undefined ? NULLABLE : String(value);
    return (
      <div className="grid gap-1.5">
        <Label htmlFor={id}>{label}</Label>
        <NativeSelect
          id={id}
          value={current}
          disabled={disabled}
          onChange={(e) => {
            const next = e.target.value;
            if (next === NULLABLE) onChange(null);
            else if (type === 'boolean') onChange(next === 'true');
            else onChange(next);
          }}
        >
          <NativeSelectOption value={NULLABLE}>{noDefault}</NativeSelectOption>
          {type === 'boolean' ? (
            <>
              <NativeSelectOption value="true">
                {t('records.type_editor.default_true', { defaultValue: 'True' })}
              </NativeSelectOption>
              <NativeSelectOption value="false">
                {t('records.type_editor.default_false', { defaultValue: 'False' })}
              </NativeSelectOption>
            </>
          ) : (
            choices
              .filter((c) => c.value)
              .map((c) => (
                <NativeSelectOption key={c.value} value={c.value}>
                  {c.label || c.value}
                </NativeSelectOption>
              ))
          )}
        </NativeSelect>
      </div>
    );
  }

  if (type === 'number' || type === 'integer') {
    return (
      <div className="grid gap-1.5">
        <Label htmlFor={id}>{label}</Label>
        <Input
          id={id}
          type="number"
          step={type === 'integer' ? 1 : 'any'}
          value={value === null || value === undefined ? '' : String(value)}
          disabled={disabled}
          onChange={(e) => {
            const raw = e.target.value;
            onChange(raw === '' ? null : Number(raw));
          }}
        />
      </div>
    );
  }

  if (type === 'datetime') {
    // A `datetime` default is stored the same as any `datetime` value — an
    // ISO string carrying an offset (the server refuses a naive one, design
    // §7.3) — so it has to go through the same local ⇄ ISO conversion the
    // record form uses, not straight through like `date`, which has no zone
    // to lose.
    const local = typeof value === 'string' ? isoToLocalInput(value) : '';
    return (
      <div className="grid gap-1.5">
        <Label htmlFor={id}>{label}</Label>
        <Input
          id={id}
          type="datetime-local"
          step="1"
          value={local}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value === '' ? null : localInputToIso(e.target.value))}
        />
      </div>
    );
  }

  const inputType = type === 'date' ? 'date' : 'text';
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={inputType}
        value={value === null || value === undefined ? '' : String(value)}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
      />
    </div>
  );
}
