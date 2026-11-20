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
import { keys, useT } from '../../utils/i18n';

/** The page's own "leave without saving?" question, shown when a navigation was held. */
export function LeaveDialog({
  open,
  onStay,
  onLeave,
}: {
  open: boolean;
  onStay: () => void;
  onLeave: () => void;
}) {
  const { t } = useT();
  const copy = keys.events.editor;
  return (
    <AlertDialog open={open} onOpenChange={(next) => !next && onStay()}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t(copy.leave_title)}</AlertDialogTitle>
          <AlertDialogDescription className="dark:text-zinc-400">
            {t(copy.leave_description)}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{t(copy.leave_stay)}</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={onLeave}>
            {t(copy.leave_confirm)}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
