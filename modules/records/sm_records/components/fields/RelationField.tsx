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
    // The render-prop form: the picker is a group of controls, not one
    // input, so it takes the shell's label id as an `aria-labelledby`
    // rather than an `htmlFor` (UX review R11).
    <FieldShell field={field} error={error}>
      {(labelId) => (
        <RelationPicker
          field={field}
          value={value}
          onChange={onChange}
          disabled={disabled}
          expanded={expanded}
          labelId={labelId}
        />
      )}
    </FieldShell>
  );
}
