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
import { type ReactNode, useState } from 'react';
import { errorText } from '../utils/api';
import { keys, useT } from '../utils/i18n';

/*
 * This wrapper owns the trigger and async lifecycle. The framework's controlled
 * `ConfirmActionDialog` can show errors with `busy` and children, but exposes
 * no trigger; replacing this wrapper also needs to preserve trigger focus.
 */
/**
 * Confirm a destructive action without `window.confirm()`, which cannot show
 * the server's reason when the confirmed action fails. A rejected `onConfirm`
 * keeps the dialog open and shows the message. A self-contained copy of the
 * same component in records and pagebuilder: modules do not import each
 * other's frontend code.
 */
export function ConfirmDialog({
  trigger,
  title,
  description,
  confirmLabel,
  onConfirm,
}: {
  trigger: ReactNode;
  title: ReactNode;
  description: string;
  confirmLabel: string;
  onConfirm: () => Promise<unknown>;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirm = async () => {
    setPending(true);
    setError(null);
    try {
      await onConfirm();
      setOpen(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setPending(false);
    }
  };

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (pending) return;
        setOpen(next);
        if (!next) setError(null);
      }}
    >
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto">
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription className="dark:text-zinc-400">
            {description}
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error && (
          <p className="text-sm text-destructive dark:text-red-400" role="alert">
            {error}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{t(keys.events.common.cancel)}</AlertDialogCancel>
          <AlertDialogAction
            disabled={pending}
            variant="destructive"
            onClick={(e) => {
              e.preventDefault();
              void confirm();
            }}
          >
            {pending ? t(keys.events.common.saving) : confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
