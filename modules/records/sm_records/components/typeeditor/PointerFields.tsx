import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { useEffect } from 'react';
import { keys, useT } from '../../utils/i18n';

import type { ValidationError } from '../../utils/types';
import { fieldMessage } from './errors';
import { displayFieldAllowed, slugFieldAllowed } from './rules';
import type { EditableField, TypeMetadataValues } from './types';

const ID = {
  displayField: 'type-editor-display-field',
  slugField: 'type-editor-slug-field',
};

/**
 * The type's two field pointers, `display_field` and `slug_field`.
 *
 * Rendered *below* the Fields card (UX review R19) rather than inside the
 * Details form: on a new type both can only say "None" until a field exists,
 * so asking for them first made the first screen of the editor unanswerable.
 * Editable on a populated type too, same as `fields` — changing either is
 * classified and dry-run like any other schema write, since `display_title`
 * and `slug` are denormalised from them onto every existing record.
 */
export function PointerFields({
  fields,
  values,
  errors,
  onChange,
}: {
  fields: EditableField[];
  values: TypeMetadataValues;
  errors: ValidationError[];
  onChange: (patch: Partial<TypeMetadataValues>) => void;
}) {
  const { t } = useT();
  const none = t(keys.records.type_editor.pointer_none);
  // Only the field types the API accepts for each pointer
  // (`services/_schema.py::DISPLAY_FIELD_TYPES`/`SLUG_FIELD_TYPES`). Offering
  // a `json` display field or a `boolean` slug field meant a 422 on save at
  // best, and — before the server checked — every record titled `{'a': 1}`
  // or slugged `true`.
  // Never an `internal` system field (`sm_nonce`, #101): it is half of every
  // link a subscriber is sent, and the server refuses it as either pointer.
  const pointable = fields.filter((f) => f.system !== 'internal');
  const displayChoices = pointable.filter((f) => displayFieldAllowed(f.type));
  const slugChoices = pointable.filter((f) => slugFieldAllowed(f.type));
  const empty = fields.length === 0;

  // A pointer's target can stop being allowed out from under it — its type
  // changed (e.g. `text` to `longtext`) after it was picked (L7). Left
  // alone, the `<select>` drops the option and falls back to showing "None"
  // while `values.displayField`/`slugField` still hold the old key, so the
  // save that follows sends a pointer the control no longer shows and the
  // server refuses it (`DISPLAY_FIELD_TYPES`/`SLUG_FIELD_TYPES`,
  // `services/_schema.py`) with an error that contradicts the screen.
  // Clearing it here keeps the visible "None" and the actual form state in
  // agreement.
  useEffect(() => {
    if (values.displayField && !displayChoices.some((f) => f.key === values.displayField)) {
      onChange({ displayField: '' });
    }
    if (values.slugField && !slugChoices.some((f) => f.key === values.slugField)) {
      onChange({ slugField: '' });
    }
  }, [displayChoices, slugChoices, values.displayField, values.slugField, onChange]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t(keys.records.type_editor.section_pointers)}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-1.5">
          <Label htmlFor={ID.displayField}>{t(keys.records.type_editor.display_field)}</Label>
          <NativeSelect
            id={ID.displayField}
            value={values.displayField}
            disabled={empty}
            onChange={(e) => onChange({ displayField: e.target.value })}
          >
            <NativeSelectOption value="">{none}</NativeSelectOption>
            {displayChoices.map((f) => (
              <NativeSelectOption key={f.key} value={f.key}>
                {f.label} ({f.key})
              </NativeSelectOption>
            ))}
          </NativeSelect>
          {empty && (
            <p className="text-sm text-muted-foreground">
              {t(keys.records.type_editor.pointer_needs_field)}
            </p>
          )}
          {!empty && (
            <p className="text-sm text-muted-foreground">
              {t(keys.records.type_editor.display_field_help)}
            </p>
          )}
          <FieldError message={fieldMessage(errors, 'display_field')} />
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor={ID.slugField}>{t(keys.records.type_editor.slug_field)}</Label>
          <NativeSelect
            id={ID.slugField}
            value={values.slugField}
            disabled={empty}
            onChange={(e) => onChange({ slugField: e.target.value })}
          >
            <NativeSelectOption value="">{none}</NativeSelectOption>
            {slugChoices.map((f) => (
              <NativeSelectOption key={f.key} value={f.key}>
                {f.label} ({f.key})
              </NativeSelectOption>
            ))}
          </NativeSelect>
          {empty && (
            <p className="text-sm text-muted-foreground">
              {t(keys.records.type_editor.pointer_needs_field)}
            </p>
          )}
          <FieldError message={fieldMessage(errors, 'slug_field')} />
        </div>
      </CardContent>
    </Card>
  );
}

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="text-sm text-destructive">{message}</p>;
}
