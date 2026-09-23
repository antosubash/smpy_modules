import { useT } from '@simple-module-py/i18n';
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
  helpFallback,
  placeholder,
}: FieldComponentProps & { inputType: string; helpFallback?: string; placeholder?: string }) {
  const id = fieldInputId(field);
  return (
    <FieldShell field={field} error={error} htmlFor={id} helpFallback={helpFallback}>
      <Input
        id={id}
        type={inputType}
        value={typeof value === 'string' ? value : ''}
        placeholder={placeholder}
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

/** The `media` field on a host with no media library (`MediaField.tsx`
 *  picks between this and the picker): the opaque id or URL the server
 *  stores, typed by hand. The field type and the 500-character cap it
 *  validates against are the same either way.
 *
 *  U18: a bare text box said nothing about what to type into it. A built-in
 *  help fallback and placeholder name the two shapes the server actually
 *  accepts (`_payload.py`'s media validator: an id or a URL), so an operator
 *  who has never read the schema docs still knows what to paste. A schema
 *  author's own `help` still wins over the fallback (`FieldShell`). */
export function MediaTextField(props: FieldComponentProps) {
  const { t } = useT();
  return (
    <StringField
      {...props}
      inputType="text"
      helpFallback={t('records.fields.media_help', {
        defaultValue: 'The media library id or the full URL of an uploaded file.',
      })}
      placeholder={t('records.fields.media_placeholder', {
        defaultValue: 'media id or https://…',
      })}
    />
  );
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
