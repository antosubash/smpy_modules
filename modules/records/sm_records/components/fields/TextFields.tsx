import { Input } from '@simple-module-py/ui/components/ui/input';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';

import { type FieldComponentProps, FieldShell, fieldInputId } from './FieldShell';

/** The five field types whose form value is a plain string differ only in the
 *  input's `type` attribute and, for `longtext`, in being a textarea. */
function StringField({
  field,
  value,
  onChange,
  error,
  disabled,
  inputType,
}: FieldComponentProps & { inputType: string }) {
  const id = fieldInputId(field);
  return (
    <FieldShell field={field} error={error} htmlFor={id}>
      <Input
        id={id}
        type={inputType}
        value={typeof value === 'string' ? value : ''}
        disabled={disabled}
        aria-invalid={!!error}
        onChange={(event) => onChange(event.target.value)}
      />
    </FieldShell>
  );
}

export function TextField(props: FieldComponentProps) {
  return <StringField {...props} inputType="text" />;
}

export function EmailField(props: FieldComponentProps) {
  return <StringField {...props} inputType="email" />;
}

export function UrlField(props: FieldComponentProps) {
  return <StringField {...props} inputType="url" />;
}

/** Phase 2 edits a media value as the opaque id or URL the server stores.
 *  Browsing a `file_storage` library is a later phase; the field type and the
 *  500-character cap it validates against do not change when that lands. */
export function MediaField(props: FieldComponentProps) {
  return <StringField {...props} inputType="text" />;
}

export function LongTextField({ field, value, onChange, error, disabled }: FieldComponentProps) {
  const id = fieldInputId(field);
  return (
    <FieldShell field={field} error={error} htmlFor={id}>
      <Textarea
        id={id}
        rows={8}
        value={typeof value === 'string' ? value : ''}
        disabled={disabled}
        aria-invalid={!!error}
        onChange={(event) => onChange(event.target.value)}
      />
    </FieldShell>
  );
}
