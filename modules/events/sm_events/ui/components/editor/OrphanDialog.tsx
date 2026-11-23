import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@simple-module-py/ui/components/ui/alert-dialog';
import { formatInstant } from '../../utils/datetime';
import { keys, useT } from '../../utils/i18n';
import type { Override } from '../../utils/types-events';

/** The changed occurrences a new schedule would leave without a match: they
 *  are removed only when the caller confirms (`drop_orphaned_overrides`). */
export function OrphanDialog({
  orphans,
  timezone,
  onConfirm,
  onCancel,
}: {
  orphans: Override[] | null;
  timezone: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t, locale } = useT();
  const copy = keys.events.preview;
  return (
    <AlertDialog open={orphans !== null} onOpenChange={(open) => !open && onCancel()}>
      <AlertDialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto">
        <AlertDialogHeader>
          <AlertDialogTitle>{t(copy.orphan_title)}</AlertDialogTitle>
          <AlertDialogDescription className="dark:text-zinc-400">
            {t(copy.orphan_description)}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <ul className="list-disc space-y-1 pl-6 text-sm">
          {orphans?.map((o) => (
            <li key={o.id}>
              {formatInstant(o.original_start, timezone, locale)} · {t(copy[`kind_${o.kind}`])}
            </li>
          ))}
        </ul>
        <AlertDialogFooter>
          <AlertDialogCancel>{t(keys.events.common.cancel)}</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            onClick={(e) => {
              e.preventDefault();
              onConfirm();
            }}
          >
            {t(copy.orphan_confirm)}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
