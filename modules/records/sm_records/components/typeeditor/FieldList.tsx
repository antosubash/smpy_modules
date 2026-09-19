import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';

import type { ValidationError } from '../../utils/types';
import { FieldRow } from './FieldRow';
import type { EditableField, TargetType } from './types';

const EMPTY_FIELD: Omit<EditableField, 'key'> = {
  type: 'text',
  label: '',
  required: false,
  unique: false,
  indexed: false,
  default: null,
  help: null,
  constraints: {},
  options: {},
};

function move<T>(list: T[], from: number, to: number): T[] {
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

/**
 * The field list editor. Phase 3 lifts the Phase 1 lock (design §16): a
 * populated type's fields are editable here too, `disabled` only reflects
 * whether a save/preview request is in flight. `originalKeys` is the field
 * keys the type had when this page loaded — the immutable-key rule (§8.7)
 * only bites those; a field added in this session can still have its key
 * fixed before the first save ever sends it.
 */
export function FieldList({
  fields,
  originalKeys,
  targetTypes,
  disabled,
  errors,
  onChange,
}: {
  fields: EditableField[];
  originalKeys: ReadonlySet<string>;
  targetTypes: TargetType[];
  disabled: boolean;
  errors: ValidationError[];
  onChange: (next: EditableField[]) => void;
}) {
  const { t } = useT();

  const updateAt = (index: number, patch: Partial<EditableField>) =>
    onChange(fields.map((f, i) => (i === index ? { ...f, ...patch } : f)));
  const removeAt = (index: number) => onChange(fields.filter((_, i) => i !== index));
  const addField = () => onChange([...fields, { key: '', ...EMPTY_FIELD }]);

  return (
    <div className="grid gap-4">
      {fields.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t('records.type_editor.no_fields', { defaultValue: 'No fields yet.' })}
        </p>
      ) : (
        <div className="grid gap-4">
          {fields.map((field, index) => (
            <FieldRow
              // biome-ignore lint/suspicious/noArrayIndexKey: fields have no stable id until a `key` is typed, and reordering swaps array entries in place rather than tracking list identity.
              key={index}
              field={field}
              index={index}
              total={fields.length}
              keyLocked={originalKeys.has(field.key)}
              siblingKeys={fields.filter((_, i) => i !== index).map((f) => f.key)}
              targetTypes={targetTypes}
              disabled={disabled}
              errors={errors}
              onChange={(patch) => updateAt(index, patch)}
              onRemove={() => removeAt(index)}
              onMoveUp={() => onChange(move(fields, index, index - 1))}
              onMoveDown={() => onChange(move(fields, index, index + 1))}
            />
          ))}
        </div>
      )}

      <div>
        <Button type="button" variant="outline" disabled={disabled} onClick={addField}>
          {t('records.type_editor.add_field', { defaultValue: 'Add field' })}
        </Button>
      </div>
    </div>
  );
}
