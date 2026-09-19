import { Input } from '@simple-module-py/ui/components/ui/input';

import { type FieldComponentProps, FieldShell, fieldInputId } from './FieldShell';

/**
 * Both numeric types are edited as **text**, not `<input type="number">`.
 *
 * A `number` is a `Numeric(19, 5)` the API serialises as a string (design
 * §7.3), and a numeric input round-trips its value through a JS double —
 * which is exactly the precision the five-decimal contract exists to keep.
 * `inputMode` still brings up the numeric keypad on a phone.
 */
function NumericInput({
  field,
  value,
  onChange,
  error,
  disabled,
  mode,
}: FieldComponentProps & { mode: 'decimal' | 'numeric' }) {
  const id = fieldInputId(field);
  return (
    <FieldShell field={field} error={error} htmlFor={id}>
      <Input
        id={id}
        type="text"
        inputMode={mode}
        value={typeof value === 'string' ? value : ''}
        disabled={disabled}
        aria-invalid={!!error}
        onChange={(event) => onChange(event.target.value)}
      />
    </FieldShell>
  );
}

export function NumberField(props: FieldComponentProps) {
  return <NumericInput {...props} mode="decimal" />;
}

export function IntegerField(props: FieldComponentProps) {
  return <NumericInput {...props} mode="numeric" />;
}
