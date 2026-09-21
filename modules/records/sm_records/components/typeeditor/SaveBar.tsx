import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useEffect, useRef } from 'react';
import { toast } from 'sonner';

import type { ValidationError } from '../../utils/types';
import { firstInvalidTarget, groupErrors, invalidFieldCount } from './errors';
import { focusInvalidTarget, isOnScreen } from './focusInvalid';

/** Named so `isOnScreen` can ask whether the refusal it just rendered is
 *  anywhere the eye is. */
const SAVE_BAR_ID = 'records-type-save-bar';

/**
 * Save, and everything a refused save has to say (UX review R6).
 *
 * Before this, a 422 on the type editor could change nothing visible at
 * all: an error keyed `__root__` — "every field needs a 'key'", the refusal
 * you get by adding a field and pressing Save before naming it — was
 * filtered out of the metadata form's errors *and* matched no field row, so
 * it was rendered nowhere, while Save simply went back to its idle label.
 * And a refusal that did name a field only opened that row, which on a
 * long schema happens off screen.
 *
 * So: the stranded messages are rendered here, beside the button that
 * appeared to do nothing; the count says how many inputs are waiting; and
 * focus travels to the first of them. The toast is deliberately conditional
 * — announcing the same sentence inline *and* as a toast is the double-up
 * R26 objected to, so it fires only when the block is somewhere the person
 * isn't: off screen already, or about to be, because we are scrolling to a
 * field row instead.
 *
 * Split out of `pages/TypeEditor.tsx` for the 300-line cap.
 */
export function SaveBar({
  errors,
  fieldKeys,
  pending,
  dirty,
  onSave,
}: {
  /** The active 422's `errors[]`, exactly as it arrived — a stable
   *  reference, so the effect below runs once per refusal rather than once
   *  per keystroke. */
  errors: ValidationError[];
  /** The draft's field keys, in row order, for attributing an error to a
   *  row and for finding the first invalid one. */
  fieldKeys: readonly string[];
  pending: boolean;
  dirty: boolean;
  onSave: () => void;
}) {
  const { t } = useT();
  const groups = groupErrors(errors, fieldKeys);
  const count = invalidFieldCount(groups);
  // Read through a ref: a key typed into a row changes `fieldKeys` on every
  // keystroke, and re-running the effect for that would yank focus back to
  // the first invalid row mid-edit.
  const keysRef = useRef(fieldKeys);
  keysRef.current = fieldKeys;

  useEffect(() => {
    if (errors.length === 0) return;
    const keys = keysRef.current;
    const refused = groupErrors(errors, keys);
    const target = firstInvalidTarget(refused, keys);
    const stranded = refused.unplaceable[0];
    if (stranded && (target !== null || !isOnScreen(SAVE_BAR_ID))) toast.error(stranded.message);
    focusInvalidTarget(target);
  }, [errors]);

  return (
    <div id={SAVE_BAR_ID} className="space-y-3">
      {groups.unplaceable.length > 0 && (
        <ul
          className="space-y-1 text-sm text-destructive"
          role="alert"
          data-testid="records-type-save-errors"
        >
          {groups.unplaceable.map((entry) => (
            <li key={`${entry.field}:${entry.message}`}>{entry.message}</li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" disabled={pending || !dirty} onClick={onSave}>
          {pending
            ? t('records.editor.saving', { defaultValue: 'Saving…' })
            : t('records.editor.save', { defaultValue: 'Save' })}
        </Button>
        {!dirty && !pending && (
          <span className="text-sm text-muted-foreground" data-testid="records-no-changes">
            {t('records.type_editor.no_changes', { defaultValue: 'No changes to save' })}
          </span>
        )}
        {count > 0 && (
          <p
            className="text-sm text-destructive"
            role="alert"
            data-testid="records-type-save-summary"
          >
            {t('records.type_editor.fields_need_attention', {
              count,
              defaultValue: '{count} field needs attention',
              defaultValue_other: '{count} fields need attention',
            })}
          </p>
        )}
      </div>
    </div>
  );
}
