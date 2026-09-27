import { useT } from '@simple-module-py/i18n';

import { type FieldComponentProps, FieldShell } from './FieldShell';
import { TextAreaField } from './TextFields';

/** The escape hatch of design §6.1: arbitrary JSON, held as *text* while it
 *  is being typed so a half-finished edit is never clobbered mid-keystroke.
 *  `utils/values.ts` parses it once, on the way out. */
export function JsonValueField(props: FieldComponentProps) {
  return <TextAreaField {...props} mono />;
}

/**
 * The registry's fallback for a `type` this build has never heard of.
 *
 * A Record Type's fields come out of the database, and a host can be running
 * an older bundle than the module that wrote them — so an unknown type is a
 * normal event, not a bug, and it must not take the whole editor down with
 * it. The value is shown read-only: this build cannot know how to edit it,
 * and it is preserved untouched on save rather than blanked.
 */
export function UnknownField({ field, value, error }: FieldComponentProps) {
  const { t } = useT();
  return (
    <FieldShell field={field} error={error}>
      <p className="text-sm text-muted-foreground">
        {t('records.fields.unknown_type', {
          defaultValue: 'This field type ({type}) is not editable in this version.',
          type: field.type,
        })}
      </p>
      <pre className="max-h-40 overflow-auto rounded-md border bg-muted p-2 text-xs">
        {JSON.stringify(value ?? null, null, 2)}
      </pre>
    </FieldShell>
  );
}
