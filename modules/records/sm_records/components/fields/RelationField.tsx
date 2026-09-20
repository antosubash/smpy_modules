import { RelationPicker } from '../RelationPicker';
import { type FieldComponentProps, FieldShell } from './FieldShell';

/** A thin wrapper so the registry stays one entry per field type and
 *  `RelationPicker` — the only field component that talks to the API — keeps
 *  its own file and its own tests' worth of surface. */
export function RelationField({
  field,
  value,
  onChange,
  error,
  disabled,
  expanded,
}: FieldComponentProps) {
  return (
    <FieldShell field={field} error={error}>
      <RelationPicker
        field={field}
        value={value}
        onChange={onChange}
        disabled={disabled}
        expanded={expanded}
      />
    </FieldShell>
  );
}
