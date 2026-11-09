import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@simple-module-py/ui/components/ui/alert-dialog';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';
import { keys, useT } from '../utils/i18n';

export function DeleteProperty({ onDelete }: { onDelete: () => Promise<void> }) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!busy) {
          setOpen(next);
          setError('');
        }
      }}
    >
      <AlertDialogTrigger asChild>
        <Button variant="destructive">{t(keys.analytics.delete)}</Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{t(keys.analytics.delete_title)}</AlertDialogTitle>
          <AlertDialogDescription>{t(keys.analytics.delete_description)}</AlertDialogDescription>
        </AlertDialogHeader>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>{t(keys.analytics.cancel)}</AlertDialogCancel>
          <AlertDialogAction
            disabled={busy}
            onClick={async (event) => {
              event.preventDefault();
              setBusy(true);
              setError('');
              try {
                await onDelete();
                setOpen(false);
              } catch (reason) {
                setError(reason instanceof Error ? reason.message : t(keys.analytics.error));
              } finally {
                setBusy(false);
              }
            }}
          >
            {t(busy ? keys.analytics.deleting : keys.analytics.delete)}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
