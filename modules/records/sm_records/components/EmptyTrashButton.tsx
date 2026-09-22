import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useState } from 'react';

import { emptyTrashDescription } from '../utils/bulk-copy';
import { ConfirmDialog } from './ConfirmDialog';

/**
 * "Empty the trash" — the Trash view's one action that needs no selection.
 *
 * Two things it has to get right, and both are about what the operator is
 * actually agreeing to.
 *
 * **What it covers.** With a filter in force the button empties *the filtered
 * part*, because that is what the screen is showing and emptying more than
 * the screen shows would be the worst possible surprise for an irreversible
 * action. So the copy says which it is (`utils/bulk-copy`), and the count is
 * the list's own `total`.
 *
 * **Typing the count**, exactly as `DeleteTypeSection` does for a type
 * delete: this is unrecoverable and unbounded — nothing here is capped by
 * `max_bulk_records` — so a plain yes/no would let a mis-click destroy a
 * trash whose size the operator never read. Typing the number is what proves
 * they read it.
 */
export function EmptyTrashButton({
  count,
  filtered,
  capped = false,
  onEmpty,
}: {
  /** The trash listing's `total` — what the operator is being shown. */
  count: number;
  /** A `filter=` is in force, so this empties only what matches it. */
  filtered: boolean;
  /** `total_capped`: the count is a floor, not the number. The typed-count
   *  guard is dropped rather than asking for a number that is not the
   *  number — the sentence says "more than" and the action is still gated by
   *  the destructive confirm. */
  capped?: boolean;
  onEmpty: (filtered: boolean) => Promise<unknown>;
}) {
  const { t } = useT();
  const [typed, setTyped] = useState('');
  const matches = capped || (typed.trim() !== '' && Number(typed) === count);
  const label = t('records.bulk.empty_trash', { defaultValue: 'Empty trash' });
  const inputId = 'records-empty-trash-confirm';
  const hintId = 'records-empty-trash-hint';
  const showMismatch = !capped && typed.trim() !== '' && !matches;

  if (count === 0) return null;

  return (
    <ConfirmDialog
      trigger={
        <Button
          type="button"
          variant="destructive"
          size="sm"
          data-testid="records-empty-trash"
          disabled={count === 0}
        >
          {label}
        </Button>
      }
      title={label}
      description={emptyTrashDescription(t, { count, filtered, capped })}
      body={
        capped ? null : (
          <div className="grid gap-2">
            <Label htmlFor={inputId}>
              {t('records.bulk.empty_trash_count_label', { defaultValue: 'Record count' })}
            </Label>
            <Input
              id={inputId}
              inputMode="numeric"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              aria-describedby={hintId}
              aria-invalid={showMismatch || undefined}
            />
            <p
              id={hintId}
              role={showMismatch ? 'alert' : undefined}
              className={
                showMismatch ? 'text-sm text-destructive' : 'text-sm text-muted-foreground'
              }
            >
              {showMismatch
                ? t('records.type_editor.delete_count_mismatch', {
                    defaultValue: "That doesn't match. Type the exact number to confirm.",
                  })
                : t('records.bulk.empty_trash_count_hint', {
                    count,
                    defaultValue: 'Type {count} to enable Empty trash.',
                  })}
            </p>
          </div>
        )
      }
      confirmLabel={label}
      cancelLabel={t('records.editor.cancel', { defaultValue: 'Cancel' })}
      pendingLabel={t('records.editor.saving', { defaultValue: 'Saving…' })}
      destructive
      confirmDisabled={!matches}
      // Reopening used to show the previous attempt's digits, which reads as
      // though the count had already been confirmed.
      onOpenChange={(open) => {
        if (!open) setTyped('');
      }}
      onConfirm={() => onEmpty(filtered)}
    />
  );
}
