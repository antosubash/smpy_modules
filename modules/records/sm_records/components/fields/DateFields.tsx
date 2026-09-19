import { Input } from '@simple-module-py/ui/components/ui/input';

import { type FieldComponentProps, FieldShell, fieldInputId } from './FieldShell';

/** `date` and `datetime` are separate index tables for a reason (design
 *  §7.3), and they are separate inputs here for the same one: a calendar date
 *  has no zone, and a timestamp must carry one. `utils/values.ts` stamps the
 *  browser's offset onto whatever `datetime-local` produces — the server
 *  refuses a naive value rather than guessing. */
function DateInput({
  field,
  value,
  onChange,
  error,
  disabled,
  inputType,
}: FieldComponentProps & { inputType: 'date' | 'datetime-local' }) {
  const id = fieldInputId(field);
  return (
    <FieldShell field={field} error={error} htmlFor={id}>
      <Input
        id={id}
        type={inputType}
        // Seconds matter for `datetime` (F4): without `step="1"` the browser
        // never shows a seconds field to type into, so anything typed by
        // hand loses them even though `isoToLocalInput` now preserves them
        // for a value opened from storage.
        step={inputType === 'datetime-local' ? '1' : undefined}
        value={typeof value === 'string' ? value : ''}
        disabled={disabled}
        aria-invalid={!!error}
        onChange={(event) => onChange(event.target.value)}
      />
    </FieldShell>
  );
}

export function DateField(props: FieldComponentProps) {
  return <DateInput {...props} inputType="date" />;
}

export function DateTimeField(props: FieldComponentProps) {
  return <DateInput {...props} inputType="datetime-local" />;
}
