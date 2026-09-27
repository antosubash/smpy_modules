import { useT } from '@simple-module-py/i18n';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';

import { type FieldComponentProps, FieldShell, fieldInputId } from './FieldShell';

/** Every field type whose form value is a plain string is an `<Input>` that
 *  differs only in its `type` and, for the numeric and date types, one extra
 *  attribute. React drops an `undefined` attribute, so a type that passes
 *  none renders exactly the bare input. */
function InputField({
  field,
  value,
  onChange,
  error,
  disabled,
  inputType,
  inputMode,
  step,
  helpFallback,
  placeholder,
}: FieldComponentProps & {
  inputType: string;
  inputMode?: 'decimal' | 'numeric';
  step?: string;
  helpFallback?: string;
  placeholder?: string;
}) {
  const id = fieldInputId(field);
  return (
    <FieldShell field={field} error={error} htmlFor={id} helpFallback={helpFallback}>
      <Input
        id={id}
        type={inputType}
        inputMode={inputMode}
        step={step}
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
  return <InputField {...props} inputType="text" />;
}

export function EmailField(props: FieldComponentProps) {
  return <InputField {...props} inputType="email" />;
}

export function UrlField(props: FieldComponentProps) {
  return <InputField {...props} inputType="url" />;
}

/**
 * Both numeric types are edited as **text**, not `<input type="number">`.
 *
 * A `number` is a `Numeric(19, 5)` the API serialises as a string (design
 * §7.3), and a numeric input round-trips its value through a JS double —
 * which is exactly the precision the five-decimal contract exists to keep.
 * `inputMode` still brings up the numeric keypad on a phone.
 */
export function NumberField(props: FieldComponentProps) {
  return <InputField {...props} inputType="text" inputMode="decimal" />;
}

export function IntegerField(props: FieldComponentProps) {
  return <InputField {...props} inputType="text" inputMode="numeric" />;
}

/** `date` and `datetime` are separate index tables for a reason (design
 *  §7.3), and they are separate inputs here for the same one: a calendar date
 *  has no zone, and a timestamp must carry one. `utils/values.ts` stamps the
 *  browser's offset onto whatever `datetime-local` produces — the server
 *  refuses a naive value rather than guessing. */
export function DateField(props: FieldComponentProps) {
  return <InputField {...props} inputType="date" />;
}

/** Seconds matter for `datetime` (F4): without `step="1"` the browser never
 *  shows a seconds field to type into, so anything typed by hand loses them
 *  even though `isoToLocalInput` now preserves them for a value opened from
 *  storage. */
export function DateTimeField(props: FieldComponentProps) {
  return <InputField {...props} inputType="datetime-local" step="1" />;
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
    <InputField
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

/** An eight-row `<Textarea>`; `mono` is the JSON field's code styling. */
export function TextAreaField({
  field,
  value,
  onChange,
  error,
  disabled,
  mono = false,
}: FieldComponentProps & { mono?: boolean }) {
  const id = fieldInputId(field);
  return (
    <FieldShell field={field} error={error} htmlFor={id}>
      <Textarea
        id={id}
        rows={8}
        value={typeof value === 'string' ? value : ''}
        disabled={disabled}
        aria-invalid={!!error}
        className={mono ? 'font-mono text-sm' : undefined}
        spellCheck={mono ? false : undefined}
        onChange={(event) => onChange(event.target.value)}
      />
    </FieldShell>
  );
}

export function LongTextField(props: FieldComponentProps) {
  return <TextAreaField {...props} />;
}
