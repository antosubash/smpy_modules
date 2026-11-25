import { useState } from 'react';
import { useMountedRef } from './useMountedRef';

/**
 * The action lifecycle shared by `ConfirmDialog` and `NoteDialog`.
 *
 * The invariants live here once, so the two dialogs cannot drift apart on
 * the same page: a request in flight owns the dialog (closing it would
 * strand the pending state and drop the error the call is about to
 * produce), a failure keeps the dialog open with the message inside it,
 * and closing clears the error so a reopened dialog starts clean.
 */
export function usePendingDialog(fallbackError: string, onClose?: () => void) {
  const mounted = useMountedRef();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Radix `onOpenChange` handler; also the Cancel button's close path. */
  const change = (next: boolean) => {
    if (pending) return;
    setOpen(next);
    if (!next) {
      setError(null);
      onClose?.();
    }
  };

  /** Run the action: close on success, keep the dialog open on failure. */
  const run = async (work: () => Promise<unknown>) => {
    setPending(true);
    setError(null);
    try {
      await work();
      if (!mounted.current) return;
      setOpen(false);
      onClose?.();
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : fallbackError);
    } finally {
      if (mounted.current) setPending(false);
    }
  };

  return { open, pending, error, change, run };
}
