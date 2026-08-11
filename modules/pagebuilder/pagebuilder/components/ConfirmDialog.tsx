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
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = (next: boolean) => {
    // A request in flight owns the dialog: closing it here would strand the
    // pending state and drop the error the call is about to produce.
    if (pending) return;
    setOpen(next);
    if (!next) setError(null);
  };

  const run = async () => {
    setPending(true);
    setError(null);
    try {
      await onConfirm();
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : `${confirmLabel} failed`);
    } finally {
      setPending(false);
    }
  };

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
              void run();
            }}
          >
            {pending ? 'Working…' : confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
