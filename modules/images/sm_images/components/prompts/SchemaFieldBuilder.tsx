import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';

import { keys, useT } from '../../utils/i18n';
import {
  emptyField,
  FIELD_TYPES,
  type FieldType,
  type SchemaField,
} from '../../utils/schemaFields';

const TYPE_LABEL = {
  string: keys.images.prompts.schema.type.string,
  integer: keys.images.prompts.schema.type.integer,
  number: keys.images.prompts.schema.type.number,
  boolean: keys.images.prompts.schema.type.boolean,
  string_list: keys.images.prompts.schema.type.string_list,
} satisfies Record<FieldType, string>;

const hasChoices = (type: FieldType) => type === 'string' || type === 'string_list';

/** A structured answer as a list of named fields (the portal's builder,
 *  extended with whole numbers and allowed values). Only ever shown for a
 *  schema `schemaToFields` can express exactly; anything else is JSON. */
export function SchemaFieldBuilder({
  fields,
  onChange,
  disabled = false,
}: {
  fields: SchemaField[];
  onChange: (fields: SchemaField[]) => void;
  disabled?: boolean;
}) {
  const { t } = useT();
  const update = (index: number, patch: Partial<SchemaField>) =>
    onChange(fields.map((f, i) => (i === index ? { ...f, ...patch } : f)));

  return (
    <div className="space-y-3" data-testid="images-schema-fields">
      {fields.map((field, index) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: rows have no stable id
          key={index}
          className="space-y-2 rounded-md border p-3"
          data-testid={`images-schema-field-${index}`}
        >
          <div className="flex items-center gap-2">
            <Input
              aria-label={t(keys.images.prompts.schema.field_name)}
              placeholder={t(keys.images.prompts.schema.field_name)}
              value={field.name}
              disabled={disabled}
              onChange={(e) => update(index, { name: e.target.value })}
            />
            <NativeSelect
              aria-label={t(keys.images.prompts.schema.field_type)}
              value={field.type}
              disabled={disabled}
              onChange={(e) => update(index, { type: e.target.value as FieldType })}
            >
              {FIELD_TYPES.map((type) => (
                <option key={type} value={type}>
                  {t(TYPE_LABEL[type])}
                </option>
              ))}
            </NativeSelect>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={disabled}
              onClick={() => onChange(fields.filter((_, i) => i !== index))}
            >
              {t(keys.images.prompts.schema.remove_field)}
            </Button>
          </div>
          <Input
            aria-label={t(keys.images.prompts.schema.description)}
            placeholder={t(keys.images.prompts.schema.description)}
            value={field.description}
            disabled={disabled}
            onChange={(e) => update(index, { description: e.target.value })}
          />
          {hasChoices(field.type) && (
            <Input
              aria-label={t(keys.images.prompts.schema.choices)}
              placeholder={t(keys.images.prompts.schema.choices)}
              value={field.choices.join(', ')}
              disabled={disabled}
              onChange={(e) =>
                // Empty entries are kept while typing ("a, ") and dropped on build.
                update(index, { choices: e.target.value.split(',').map((c) => c.trimStart()) })
              }
            />
          )}
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={field.required}
              disabled={disabled}
              onChange={(e) => update(index, { required: e.target.checked })}
            />
            {t(keys.images.prompts.schema.required)}
          </label>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        data-testid="images-schema-add-field"
        onClick={() => onChange([...fields, emptyField()])}
      >
        {t(keys.images.prompts.schema.add_field)}
      </Button>
    </div>
  );
}
