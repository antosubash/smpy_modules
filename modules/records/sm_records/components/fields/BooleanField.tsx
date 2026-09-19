import { Switch } from '@simple-module-py/ui/components/ui/switch';

import { type FieldComponentProps, FieldShell, fieldInputId } from './FieldShell';

/**
 * A tri-state in the model, a two-state on screen.
 *
 * The form value is `boolean | null`, where `null` means "never set". A
 * record whose optional flag was never given a value should not acquire a
 * `false` merely because someone opened the editor and saved — so `null`
 * renders unchecked but is written back as *nothing at all*
 * (`toApiValue` returns `undefined` for it). The first toggle commits to a
 * real boolean, which is the only way to reach `false` deliberately.
 */
export function BooleanField({ field, value, onChange, error, disabled }: FieldComponentProps) {
  const id = fieldInputId(field);
  return (
    <FieldShell field={field} error={error} htmlFor={id}>
      <Switch
        id={id}
        checked={value === true}
        disabled={disabled}
        aria-invalid={!!error}
        onCheckedChange={(checked) => onChange(checked)}
      />
    </FieldShell>
  );
}
