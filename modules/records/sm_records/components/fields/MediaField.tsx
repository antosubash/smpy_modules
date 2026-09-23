import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';

import type { MediaApi } from '../../utils/media-api';
import { useMediaApi } from '../media/MediaApiContext';
import { MediaPickerDialog } from '../media/MediaPickerDialog';
import { MediaPreview } from '../media/MediaPreview';
import { type FieldComponentProps, FieldShell, fieldInputId } from './FieldShell';
import { MediaTextField } from './TextFields';

/** The picker: the stored file as a thumbnail or a chip, and the buttons that
 *  change it. The value is the file's id — never its URL, which is derived
 *  from `file_url_template` wherever the file is shown (`utils/media-api.ts`). */
function MediaPickerField({
  api,
  field,
  value,
  onChange,
  error,
  disabled,
}: FieldComponentProps & { api: MediaApi }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const id = fieldInputId(field);
  const stored = typeof value === 'string' ? value.trim() : '';
  const actionTextId = `${id}-action`;

  return (
    <FieldShell
      field={field}
      error={error}
      helpFallback={t('records.fields.media_picker_help', {
        defaultValue: 'Choose a file from the media library, or upload one.',
      })}
    >
      {(labelId) => (
        <fieldset
          aria-labelledby={labelId}
          className="grid min-w-0 gap-2 rounded-md border p-3"
          data-testid={`records-media-field-${field.key}`}
        >
          {stored ? (
            <MediaPreview api={api} value={stored} variant="field" />
          ) : (
            <p className="text-sm text-muted-foreground" data-testid="records-media-none">
              {t('records.media.none', { defaultValue: 'No file chosen.' })}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {/* One button for Choose and Replace, not two: Radix returns focus
                to the element that opened the dialog, and a Choose that
                became a different Replace node on pick would drop it on the
                page body. Named with the field's label as well, so two media
                fields on one form do not offer two identical "Choose" buttons. */}
            <Button
              id={id}
              type="button"
              variant="outline"
              disabled={disabled}
              aria-invalid={!!error}
              aria-labelledby={`${actionTextId} ${labelId}`}
              onClick={() => setOpen(true)}
              data-testid="records-media-choose"
            >
              <span id={actionTextId}>
                {stored
                  ? t('records.media.replace', { defaultValue: 'Replace…' })
                  : t('records.media.choose', { defaultValue: 'Choose file…' })}
              </span>
            </Button>
            {stored && (
              <Button
                type="button"
                variant="ghost"
                disabled={disabled}
                aria-labelledby={`${id}-remove ${labelId}`}
                onClick={() => {
                  onChange('');
                  // The button that held focus is gone; keep it in the field.
                  window.requestAnimationFrame(() => document.getElementById(id)?.focus());
                }}
                data-testid="records-media-remove"
              >
                <span id={`${id}-remove`}>
                  {t('records.media.remove', { defaultValue: 'Remove' })}
                </span>
              </Button>
            )}
          </div>
          <MediaPickerDialog
            api={api}
            open={open}
            currentId={stored || null}
            onOpenChange={setOpen}
            onPick={(file) => onChange(file.id)}
          />
        </fieldset>
      )}
    </FieldShell>
  );
}

/**
 * The `media` field: a picker over the host's media library when the page
 * was handed a `media_api` (`sm_records.media` found one at startup), and the
 * plain id-or-URL text box otherwise — the same box, hint and placeholder it
 * has always been, so a host with no library loses nothing.
 */
export function MediaField(props: FieldComponentProps) {
  const api = useMediaApi();
  if (!api) return <MediaTextField {...props} />;
  return <MediaPickerField {...props} api={api} />;
}
