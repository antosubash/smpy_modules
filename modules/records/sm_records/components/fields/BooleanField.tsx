import { useT } from '@simple-module-py/i18n';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { Switch } from '@simple-module-py/ui/components/ui/switch';

import { type FieldComponentProps, FieldShell, fieldInputId } from './FieldShell';

/**
 * A tri-state in the model, and — since R7 — a tri-state on screen too.
 *
 * The form value is `boolean | null`, where `null` means "never set". A
 * record whose optional flag was never given a value should not acquire a
 * `false` merely because someone opened the editor and saved — so `null`
 * is written back as *nothing at all* (`toApiValue` returns `undefined` for
 * it). That part was right; what the person saw was not.
 *
 * A **required** boolean that was never set rendered as a switch plainly in
 * the "off" position under the message "This field is required", because
 * `checked={value === true}` cannot draw the difference between `null` and
 * `false`. The only way out was toggling on and back off — an interaction
 * nothing on screen suggests. So a required boolean is a select: "not set"
 * while it is, then Yes / No. The unset option disappears once a real value
 * is chosen, because the field is required and going back is not a state
 * the server accepts.
 *
 * An optional boolean keeps the switch — the control suits a flag people
 * flip — but says "Not set" beside it while that is what it is, instead of
 * showing the same thing "No" would show.
 */
export function BooleanField({ field, value, onChange, error, disabled }: FieldComponentProps) {
  const { t } = useT();
  const id = fieldInputId(field);
  const unset = value !== true && value !== false;

  if (field.required) {
    return (
      <FieldShell field={field} error={error} htmlFor={id}>
        <NativeSelect
          id={id}
          value={unset ? '' : String(value)}
          disabled={disabled}
          aria-invalid={!!error}
          data-testid={`records-boolean-${field.key}`}
          onChange={(event) => {
            const next = event.target.value;
            onChange(next === '' ? null : next === 'true');
          }}
        >
          {unset && (
            <NativeSelectOption value="">
              {t('records.fields.boolean_unset', { defaultValue: 'Not set' })}
            </NativeSelectOption>
          )}
          <NativeSelectOption value="true">
            {t('records.fields.boolean_yes', { defaultValue: 'Yes' })}
          </NativeSelectOption>
          <NativeSelectOption value="false">
            {t('records.fields.boolean_no', { defaultValue: 'No' })}
          </NativeSelectOption>
        </NativeSelect>
      </FieldShell>
    );
  }

  return (
    <FieldShell field={field} error={error} htmlFor={id}>
      <div className="flex items-center gap-2">
        <Switch
          id={id}
          checked={value === true}
          disabled={disabled}
          aria-invalid={!!error}
          onCheckedChange={(checked) => onChange(checked)}
        />
        {unset && (
          <span
            className="text-sm text-muted-foreground"
            data-testid={`records-unset-${field.key}`}
          >
            {t('records.fields.boolean_unset', { defaultValue: 'Not set' })}
          </span>
        )}
      </div>
    </FieldShell>
  );
}
