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
import type { ReactNode } from 'react';

import { usePendingDialog } from '../hooks/usePendingDialog';

/**
 * Confirm a consequential action without handing the page to the browser.
 *
 * `confirm()` blocks the event loop, cannot say which row it is asking about
 * beyond a bare sentence, is unstyleable, and — the reason it matters here —
 * gives the failure nowhere to go: the call site learns the user said yes and
 * then swallows whatever the request answered. This keeps the dialog open
 * while the work runs and shows the error inside it, so a delete that comes
 * back 403 is visible instead of looking like it worked.
 */
export function ConfirmDialog({
  trigger,
  title,
  description,
  confirmLabel = 'Confirm',
  destructive = false,
  onConfirm,
}: {
  trigger: ReactNode;
  title: string;
  description: ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
  /** Rejecting keeps the dialog open and surfaces the message. */
  onConfirm: () => Promise<unknown>;
}) {
  // The open/pending/error lifecycle is shared with NoteDialog — see the
  // hook for the invariants (in-flight request owns the dialog, failure
  // keeps it open, closing clears the error).
  const { open, pending, error, change, run } = usePendingDialog(`${confirmLabel} failed`);

  return (
    <AlertDialog open={open} onOpenChange={change}>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={pending}
            className={destructive ? 'bg-destructive text-white hover:bg-destructive/90' : ''}
            // Radix closes on click; the close has to wait for the request so
            // a failure stays on screen.
            onClick={(e) => {
              e.preventDefault();
              void run(onConfirm);
            }}
          >
            {pending ? 'Working…' : confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
