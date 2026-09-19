import { useT } from '@simple-module-py/i18n';
import { Label } from '@simple-module-py/ui/components/ui/label';
import type { ReactElement, ReactNode } from 'react';

import type { FieldDef } from '../../utils/types';

/**
 * The contract every field component in this directory implements, and the
 * label/help/error chrome they all share.
 *
 * `value` and the argument to `onChange` are `unknown` on purpose: each
 * component knows its own form shape (a string, a `string[]`, a relation
 * object) and `utils/values.ts` owns the conversion to and from the wire.
 * Typing the registry map to a union of those shapes would make
 * `getFieldComponent` — which is handed a `type` string that came out of the
 * database — unusable without a cast at every call site.
 */
export type FieldComponentProps = {
  field: FieldDef;
  value: unknown;
  onChange: (next: unknown) => void;
  error?: string;
  disabled?: boolean;
};

export type FieldComponent = (props: FieldComponentProps) => ReactElement;

/** Not a translatable string — a typographic marker, with the word itself
 *  carried next to it for a screen reader. */
const REQUIRED_MARK = '*';

export function fieldInputId(field: FieldDef): string {
  return `record-field-${field.key}`;
}

export function FieldShell({
  field,
  error,
  htmlFor,
  children,
}: {
  field: FieldDef;
  error?: string;
  /** Omitted when the control is a group (checkbox list, chips) rather than
   *  one focusable input — the group gets an `aria-labelledby` instead. */
  htmlFor?: string;
  children: ReactNode;
}) {
  const { t } = useT();
  const labelId = `${fieldInputId(field)}-label`;
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={htmlFor} id={labelId}>
        <span>{field.label}</span>
        {field.required && (
          <>
            <span className="text-destructive" aria-hidden="true">
              {REQUIRED_MARK}
            </span>
            <span className="sr-only">
              {t('records.fields.required', { defaultValue: 'Required' })}
            </span>
          </>
        )}
      </Label>
      {field.help && <p className="text-sm text-muted-foreground">{field.help}</p>}
      {children}
      {error && (
        <p
          className="text-sm text-destructive"
          role="alert"
          data-testid={`records-field-error-${field.key}`}
        >
          {error}
        </p>
      )}
    </div>
  );
}
