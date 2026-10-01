import { useT } from '@simple-module-py/i18n';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';

import { choicesOf } from '../../utils/values';
import { type FieldComponentProps, FieldShell, fieldInputId } from './FieldShell';

export function SelectField({ field, value, onChange, error, disabled }: FieldComponentProps) {
  const { t } = useT();
  const id = fieldInputId(field);
  const choices = choicesOf(field);
  return (
    <FieldShell field={field} error={error} htmlFor={id}>
      <NativeSelect
        id={id}
        className="w-full"
        value={typeof value === 'string' ? value : ''}
        disabled={disabled}
        aria-invalid={!!error}
        onChange={(event) => onChange(event.target.value)}
      >
        {/* Always offered, even on a required field: without it a required
            select silently submits its first choice for someone who never
            looked at it, which is worse than a validation message. */}
        <NativeSelectOption value="">
          {t('records.fields.choose', { defaultValue: '— choose —' })}
        </NativeSelectOption>
        {choices.map((choice) => (
          <NativeSelectOption key={choice.value} value={choice.value}>
            {choice.label}
          </NativeSelectOption>
        ))}
      </NativeSelect>
    </FieldShell>
  );
}

/** A checkbox list rather than a multi-`<select>`: the native control hides
 *  what is selected behind a scroll box and needs ctrl-click to deselect. */
export function MultiSelectField({ field, value, onChange, error, disabled }: FieldComponentProps) {
  const { t } = useT();
  const selected = Array.isArray(value)
    ? value.filter((v): v is string => typeof v === 'string')
    : [];
  const choices = choicesOf(field);
  const groupId = fieldInputId(field);

  const toggle = (choiceValue: string, checked: boolean) => {
    if (!checked) {
      onChange(selected.filter((item) => item !== choiceValue));
      return;
    }
    if (selected.includes(choiceValue)) return;
    // Re-order to the schema's own choice order rather than appending at the
    // end: unchecking then re-checking a value used to move it past every
    // choice checked in between, even though its checkbox never moved on
    // screen. A value that is no longer (or never was) a real choice — data
    // from before the schema changed — keeps its place at the end instead of
    // being dropped.
    const known = new Set(choices.map((c) => c.value));
    const withNext = new Set([...selected, choiceValue]);
    const ordered = choices.map((c) => c.value).filter((v) => withNext.has(v));
    const unknown = selected.filter((v) => !known.has(v));
    onChange([...ordered, ...unknown]);
  };

  return (
    <FieldShell field={field} error={error}>
      <fieldset
        aria-labelledby={`${groupId}-label`}
        aria-invalid={!!error}
        className="grid gap-2 rounded-md border p-3"
      >
        {choices.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {t('records.fields.no_choices', { defaultValue: 'This field has no choices yet.' })}
          </p>
        )}
        {choices.map((choice, index) => {
          // Indexed, not `${groupId}-${choice.value}`: a choice value with a
          // space or a `#` in it makes an id that `htmlFor` still resolves
          // but `querySelector` cannot (polish note). The list is a fixed
          // array from the schema, so the index is stable for the render
          // that uses it; React still keys the row by `choice.value`.
          const boxId = `${groupId}-${index}`;
          return (
            <div key={choice.value} className="flex items-center gap-2">
              <Checkbox
                id={boxId}
                checked={selected.includes(choice.value)}
                disabled={disabled}
                onCheckedChange={(checked) => toggle(choice.value, checked === true)}
              />
              <Label htmlFor={boxId} className="font-normal">
                {choice.label}
              </Label>
            </div>
          );
        })}
      </fieldset>
    </FieldShell>
  );
}
