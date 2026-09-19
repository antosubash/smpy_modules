import { useT } from '@simple-module-py/i18n';

import type { FieldDef } from '../utils/types';
import type { FormValues } from '../utils/values';
import { getFieldComponent } from './fields';

/** The field loop, extracted from `RecordEditor` so the page keeps room for
 *  the save/conflict machinery under the 300-line cap. Fields render in the
 *  order the type declares them; nothing here knows any field type. */
export function RecordForm({
  fields,
  values,
  errors,
  disabled,
  onChange,
}: {
  fields: FieldDef[];
  values: FormValues;
  errors: Record<string, string>;
  disabled?: boolean;
  onChange: (key: string, next: unknown) => void;
}) {
  const { t } = useT();
  if (fields.length === 0) {
    return (
      <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
        {t('records.form.no_fields', {
          defaultValue: 'This type has no fields yet. Add some on its schema screen.',
        })}
      </p>
    );
  }
  return (
    <div className="grid gap-5">
      {fields.map((field) => {
        const Field = getFieldComponent(field.type);
        return (
          <Field
            key={field.key}
            field={field}
            value={values[field.key]}
            error={errors[field.key]}
            disabled={disabled}
            onChange={(next) => onChange(field.key, next)}
          />
        );
      })}
    </div>
  );
}
