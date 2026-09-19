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
    const next = checked
      ? [...selected.filter((item) => item !== choiceValue), choiceValue]
      : selected.filter((item) => item !== choiceValue);
    onChange(next);
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
        {choices.map((choice) => {
          const boxId = `${groupId}-${choice.value}`;
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
