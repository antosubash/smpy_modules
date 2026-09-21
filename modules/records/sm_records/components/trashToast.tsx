import { Link } from '@inertiajs/react';
import { toast } from 'sonner';

// See `pages/RecordList.tsx` for why `t` is typed this loosely here.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

/**
 * The confirmation a soft delete owes the person who confirmed it (UX-R8).
 *
 * Deleting a record used to be entirely silent: the row vanished, nothing
 * said where it went, and nothing said it could be brought back — a
 * reversible action presented as an irreversible one, on a module whose
 * Trash is a toolbar toggle most users have never pressed.
 *
 * So: one toast that names the Trash, with "Undo" restoring the record in
 * place (sonner's own `action`) and a link to the trashed view of this type
 * for the person who notices a minute later instead of a second later.
 */
export function trashToast(
  t: Translate,
  { typeKey, onUndo }: { typeKey: string; onUndo: () => Promise<unknown> },
): void {
  toast.success(t('records.records.trashed', { defaultValue: 'Moved to the Trash' }), {
    description: (
      <Link href={`/admin/records/${typeKey}?trashed=true`} className="underline">
        {t('records.records.view_trash', { defaultValue: 'View trash' })}
      </Link>
    ),
    action: {
      label: t('records.records.undo', { defaultValue: 'Undo' }),
      onClick: () => {
        void onUndo();
      },
    },
  });
}

/** The other half of the pair: what "Undo" says when it worked. Separate
 *  from the delete toast so the restore path in the editor (where the record
 *  is restored from its own screen, not from a toast) can use it too. */
export function restoredToast(t: Translate): void {
  toast.success(t('records.records.restored', { defaultValue: 'Record restored' }));
}
