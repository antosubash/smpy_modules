import { useT } from '@simple-module-py/i18n';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';

import { ChoicesEditor } from './ChoicesEditor';
import { DefaultInput } from './DefaultInput';
import { RelationOptions } from './RelationOptions';
import {
  type Choice,
  type EditableField,
  NUMERIC_TYPES,
  ON_DELETE_DEFAULT,
  type TargetType,
  TEXT_LIKE_TYPES,
} from './types';

function numberField(
  id: string,
  label: string,
  value: unknown,
  onChange: (next: number | undefined) => void,
  disabled: boolean,
) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type="number"
        value={value === undefined || value === null ? '' : String(value)}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
      />
    </div>
  );
}

/** `constraints`/`options`/`default` for one field, dispatched by `type` —
 *  mirrors the per-type shapes `schema/fields.py` validates (design §6.1). */
export function FieldOptions({
  field,
  index,
  targetTypes,
  onChange,
  disabled = false,
}: {
  field: EditableField;
  /** The row's position in the field list — used for every input `id` here
   *  (L5), the same `field-row-${index}` scheme `FieldRow` itself uses.
   *  `field.key` is empty on a freshly-added row and can legitimately
   *  duplicate mid-edit (`keyValid` flags it but does not prevent it), so
   *  deriving ids from it collided across rows; the index never does. */
  index: number;
  targetTypes: TargetType[];
  onChange: (patch: Partial<EditableField>) => void;
  disabled?: boolean;
}) {
  const { t } = useT();
  const idBase = `field-row-${index}`;
  const setConstraint = (name: string, value: unknown) =>
    onChange({ constraints: { ...field.constraints, [name]: value } });
  const setOptions = (patch: Record<string, unknown>) =>
    onChange({ options: { ...field.options, ...patch } });

  const isTextLike = (TEXT_LIKE_TYPES as readonly string[]).includes(field.type);
  const isNumeric = (NUMERIC_TYPES as readonly string[]).includes(field.type);
  const choices = (field.options.choices as Choice[] | undefined) ?? [];

  return (
    <div className="grid gap-3 border-t pt-3">
      {isTextLike && (
        <div className="grid gap-3 sm:grid-cols-3">
          {numberField(
            `${idBase}-min-length`,
            t('records.type_editor.min_length', { defaultValue: 'Minimum length' }),
            field.constraints.min_length,
            (v) => setConstraint('min_length', v),
            disabled,
          )}
          {numberField(
            `${idBase}-max-length`,
            t('records.type_editor.max_length', { defaultValue: 'Maximum length' }),
            field.constraints.max_length,
            (v) => setConstraint('max_length', v),
            disabled,
          )}
          <div className="grid gap-1.5">
            <Label htmlFor={`${idBase}-pattern`}>
              {t('records.type_editor.pattern', { defaultValue: 'Pattern (regex)' })}
            </Label>
            <Input
              id={`${idBase}-pattern`}
              value={(field.constraints.pattern as string | undefined) ?? ''}
              disabled={disabled}
              onChange={(e) => setConstraint('pattern', e.target.value || undefined)}
            />
          </div>
        </div>
      )}

      {isNumeric && (
        <div className="grid gap-3 sm:grid-cols-2">
          {numberField(
            `${idBase}-min`,
            t('records.type_editor.min', { defaultValue: 'Minimum' }),
            field.constraints.min,
            (v) => setConstraint('min', v),
            disabled,
          )}
          {numberField(
            `${idBase}-max`,
            t('records.type_editor.max', { defaultValue: 'Maximum' }),
            field.constraints.max,
            (v) => setConstraint('max', v),
            disabled,
          )}
        </div>
      )}

      {(field.type === 'select' || field.type === 'multiselect') && (
        <ChoicesEditor
          fieldKey={field.key || idBase}
          choices={choices}
          disabled={disabled}
          onChange={(next) => setOptions({ choices: next })}
        />
      )}

      {field.type === 'relation' && (
        <RelationOptions
          index={index}
          targetType={(field.options.target_type as string | undefined) ?? ''}
          many={(field.options.many as boolean | undefined) ?? false}
          onDelete={
            (field.options.on_delete as 'restrict' | 'set_null' | 'cascade' | undefined) ??
            ON_DELETE_DEFAULT
          }
          targetTypes={targetTypes}
          disabled={disabled}
          onChange={(patch) =>
            setOptions({
              ...(patch.targetType !== undefined ? { target_type: patch.targetType } : {}),
              ...(patch.many !== undefined ? { many: patch.many } : {}),
              ...(patch.onDelete !== undefined ? { on_delete: patch.onDelete } : {}),
            })
          }
        />
      )}

      <DefaultInput
        index={index}
        type={field.type}
        value={field.default}
        choices={choices}
        disabled={disabled}
        onChange={(next) => onChange({ default: next })}
      />
    </div>
  );
}
