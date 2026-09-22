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
 * **Typing something**, exactly as `DeleteTypeSection` does for a type
 * delete: this is unrecoverable and unbounded — nothing here is capped by
 * `max_bulk_records` — so a plain yes/no would let a mis-click destroy a
 * trash whose size the operator never read.
 *
 * *What* they type depends on whether there is a number to speak of. Below
 * `max_count` it is the exact count, which is what proves they read it. At or
 * above it the listing's `total` is a floor rather than a total (`capped`),
 * and asking for a number that is not the number would teach people to type
 * whatever the dialog shows; so the guard asks for the **type's key**
 * instead, the way a repository host asks for a repository name. Dropping the
 * guard there would leave the largest, least reversible case as the only one
 * a single mis-click can reach.
 */
export function EmptyTrashButton({
  count,
  typeKey,
  filtered,
  capped = false,
  onEmpty,
}: {
  /** The trash listing's `total` — what the operator is being shown. */
  count: number;
  /** The type's key: what the capped case asks to be typed, and what the
   *  sentence names. */
  typeKey: string;
  /** A `filter=` is in force, so this empties only what matches it. */
  filtered: boolean;
  /** `total_capped`: the count is a floor, not the number — the sentence says
   *  "more than" and the guard switches from the count to the type key. */
  capped?: boolean;
  onEmpty: (filtered: boolean) => Promise<unknown>;
}) {
  const { t } = useT();
  const [typed, setTyped] = useState('');
  const entered = typed.trim();
  // The key is compared as text and the count as a number: `012` is the
  // count, ` product ` is the key, and neither is a different answer.
  const matches = capped ? entered === typeKey : entered !== '' && Number(entered) === count;
  const label = t('records.bulk.empty_trash', { defaultValue: 'Empty trash' });
  const inputId = 'records-empty-trash-confirm';
  const hintId = 'records-empty-trash-hint';
  const showMismatch = entered !== '' && !matches;

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
      description={emptyTrashDescription(t, { count, filtered, capped, typeKey })}
      body={
        <div className="grid gap-2">
          <Label htmlFor={inputId}>
            {capped
              ? t('records.bulk.empty_trash_key_label', { defaultValue: 'Record type key' })
              : t('records.bulk.empty_trash_count_label', { defaultValue: 'Record count' })}
          </Label>
          <Input
            id={inputId}
            data-testid="records-empty-trash-input"
            {...(capped ? {} : { inputMode: 'numeric' as const })}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            aria-describedby={hintId}
            aria-invalid={showMismatch || undefined}
          />
          <p
            id={hintId}
            role={showMismatch ? 'alert' : undefined}
            className={showMismatch ? 'text-sm text-destructive' : 'text-sm text-muted-foreground'}
          >
            {mismatchOrHint(t, { capped, count, typeKey, showMismatch })}
          </p>
        </div>
      }
      confirmLabel={label}
      cancelLabel={t('records.editor.cancel', { defaultValue: 'Cancel' })}
      pendingLabel={t('records.editor.saving', { defaultValue: 'Saving…' })}
      destructive
      confirmDisabled={!matches}
      // Reopening used to show the previous attempt's digits, which reads as
      // though the confirmation had already been given.
      onOpenChange={(open) => {
        if (!open) setTyped('');
      }}
      onConfirm={() => onEmpty(filtered)}
    />
  );
}

// biome-ignore lint/suspicious/noExplicitAny: matches `useT()`'s own signature
type Translate = (...args: any[]) => string;

/** The line under the box: what to type, or that what was typed is not it.
 *  Four sentences rather than two with a substituted noun — "Type product"
 *  and "Type 12" do not decline the same way in every language. */
function mismatchOrHint(
  t: Translate,
  {
    capped,
    count,
    typeKey,
    showMismatch,
  }: { capped: boolean; count: number; typeKey: string; showMismatch: boolean },
): string {
  if (capped) {
    return showMismatch
      ? t('records.bulk.empty_trash_key_mismatch', {
          key: typeKey,
          defaultValue: "That doesn't match. Type {key} to confirm.",
        })
      : t('records.bulk.empty_trash_key_hint', {
          key: typeKey,
          defaultValue: 'Type {key} to enable Empty trash.',
        });
  }
  return showMismatch
    ? t('records.type_editor.delete_count_mismatch', {
        defaultValue: "That doesn't match. Type the exact number to confirm.",
      })
    : t('records.bulk.empty_trash_count_hint', {
        count,
        defaultValue: 'Type {count} to enable Empty trash.',
      });
}
