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

/** `type` is the field's declared type — the picker notes the one kind it
 *  cannot show to visitors (`media`). */
export type FieldOption = { value: string; label: string; type?: string };

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

  // A `media` value renders on a public page only through the listing's
  // `media_url_template`, which is null unless the host lets visitors
  // download files — on a stock host it renders nothing, and a ticked option
  // that silently shows nothing read as a bug in the editor (review 4, ux F8).
  const mediaNote = t('records.widget.media_not_public', {
    defaultValue:
      'Not shown on public pages unless the media library lets visitors download files.',
  });

  return (
    <div className="space-y-1">
      {options.map((option) => {
        const noteId = `records-widget-field-note-${option.value}`;
        const media = option.type === 'media';
        return (
          <div key={option.value}>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={selected.includes(option.value)}
                disabled={readOnly}
                aria-describedby={media ? noteId : undefined}
                onChange={(event) => toggle(option.value, event.target.checked)}
              />
              {option.label}
            </label>
            {media && (
              <p
                id={noteId}
                className="ml-6 text-xs text-gray-500"
                data-testid="records-widget-media-note"
              >
                {mediaNote}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
