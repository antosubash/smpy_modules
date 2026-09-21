import { useT } from '@simple-module-py/i18n';
import { Label } from '@simple-module-py/ui/components/ui/label';
import type { ReactElement, ReactNode } from 'react';

import type { ExpandedRef, FieldDef } from '../../utils/types';

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
  /** This field's slice of the record's `expanded` (design §9) — only
   *  meaningful to `RelationField`; every other component ignores it. */
  expanded?: ExpandedRef[];
};

export type FieldComponent = (props: FieldComponentProps) => ReactElement;

/** Not a translatable string — a typographic marker, with the word itself
 *  carried next to it for a screen reader. */
const REQUIRED_MARK = '*';

/** The id of a schema field's input, from its key alone — what the editor
 *  needs to take the person to a field it only knows by name (UX review R6,
 *  and the 409 that names a `unique` field, R8b). */
export function fieldIdForKey(key: string): string {
  return `record-field-${key}`;
}

export function fieldInputId(field: FieldDef): string {
  return fieldIdForKey(field.key);
}

/** The id of a field's `<Label>`, for the group controls (a checkbox list, a
 *  relation picker) that have no single input to point `htmlFor` at and take
 *  an `aria-labelledby` instead (R11). */
export function fieldLabelId(field: FieldDef): string {
  return `${fieldInputId(field)}-label`;
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
  /** A render prop for the children that need that `aria-labelledby`: the
   *  shell computes the label's id, so it is the shell that has to hand it
   *  over. `RelationField` was the one child that needed it and could not
   *  get it, which is why a relation field had no accessible name at all
   *  (R11). */
  children: ReactNode | ((labelId: string) => ReactNode);
}) {
  const { t } = useT();
  const labelId = fieldLabelId(field);
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
      {typeof children === 'function' ? children(labelId) : children}
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
