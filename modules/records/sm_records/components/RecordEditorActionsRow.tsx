import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';

import type { RecordRead } from '../utils/types';
import { RecordActions } from './RecordActions';

/**
 * The button row under the form: Save, "Save as copy" (Missing-item),
 * Delete/Restore/Purge, and the error-count summary (U5). Split out of
 * `RecordEditor` for the 300-line cap — this is pure layout over state the
 * page already owns, nothing here reaches for its own data.
 */
export function RecordEditorActionsRow({
  typeKey,
  current,
  pending,
  errorCount,
  allowNavigation,
  onRestored,
  onGone,
  onDuplicate,
}: {
  typeKey: string;
  current: RecordRead | null;
  pending: boolean;
  errorCount: number;
  allowNavigation?: () => void;
  onRestored: (restored: RecordRead) => void;
  onGone: () => void;
  /** "Save as copy": stashes `current` (minus its `unique` fields) and
   *  visits `/…/{key}/new`. Absent — the button is hidden — on a brand-new
   *  record, since there is nothing yet to copy. */
  onDuplicate: () => void;
}) {
  const { t } = useT();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button type="submit" disabled={pending}>
        {pending
          ? t('records.editor.saving', { defaultValue: 'Saving…' })
          : t('records.editor.save', { defaultValue: 'Save' })}
      </Button>

      {/* Opens a prefilled `/…/new` rather than resetting in place, so the
          record being copied *from* is never at risk of being overwritten
          by a slip. */}
      {current && (
        <Button
          type="button"
          variant="outline"
          data-testid="records-editor-duplicate"
          onClick={onDuplicate}
        >
          {t('records.editor.duplicate', { defaultValue: 'Save as copy' })}
        </Button>
      )}

      {current && (
        <RecordActions
          typeKey={typeKey}
          record={current}
          allowNavigation={allowNavigation}
          onRestored={onRestored}
          onGone={onGone}
        />
      )}

      {/* A save refused by the client validator — or, since U5, by the
          server (a 422 or a 409 collision) — used to change nothing the
          person could see from here beyond the inline error, which may be a
          screen above (R6). This says how many, beside the button that
          appeared to do nothing, the same way regardless of which side
          found the problem. */}
      {errorCount > 0 && (
        <p className="text-sm text-destructive" role="alert" data-testid="records-save-summary">
          {t('records.editor.fields_need_attention', {
            count: errorCount,
            defaultValue: '{count} field needs attention',
            defaultValue_other: '{count} fields need attention',
          })}
        </p>
      )}
    </div>
  );
}
