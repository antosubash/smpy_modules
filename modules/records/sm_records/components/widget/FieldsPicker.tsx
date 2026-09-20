/**
 * Custom Puck field: which of the type's declared fields to show, in order,
 * beyond `display_title` (which always renders).
 *
 * Puck's built-in `Field` union has no "multiselect" variant (`text`,
 * `select`, `radio`, `array`, `object`, `external`, `custom`, `slot`) — see
 * `@puckeditor/core`'s `Field` type — so this is a `type: 'custom'` field,
 * the same escape hatch `blocks/Image.tsx`'s `src` field uses for its media
 * picker. Its option list isn't declared statically: `RecordsListBlock.tsx`'s
 * `resolveFields` stamps the current type's field list onto the field object
 * itself as `availableFields`, because a `CustomField`'s `render` only ever
 * receives `{ field, value, onChange, readOnly }` — no sibling props — so
 * this is the one channel available to hand it data computed from `typeKey`.
 */

import type { CustomField } from '@puckeditor/core';
import { useT } from '@simple-module-py/i18n';

export type FieldOption = { value: string; label: string };

export type FieldsPickerField = CustomField<string[]> & {
  availableFields?: FieldOption[];
};

export function FieldsPicker({
  field,
  value,
  onChange,
  readOnly,
}: {
  field: FieldsPickerField;
  value: string[] | undefined;
  onChange: (value: string[]) => void;
  readOnly?: boolean;
}) {
  const { t } = useT();
  const options = field.availableFields ?? [];
  const selected = value ?? [];

  if (options.length === 0) {
    return (
      <p className="text-xs text-gray-500">
        {t('records.widget.fields_picker_empty', {
          defaultValue: 'Pick a record type above to choose its fields.',
        })}
      </p>
    );
  }

  function toggle(key: string, checked: boolean) {
    onChange(checked ? [...selected, key] : selected.filter((k) => k !== key));
  }

  return (
    <div className="space-y-1">
      {options.map((option) => (
        <label key={option.value} className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={selected.includes(option.value)}
            disabled={readOnly}
            onChange={(event) => toggle(option.value, event.target.checked)}
          />
          {option.label}
        </label>
      ))}
    </div>
  );
}
