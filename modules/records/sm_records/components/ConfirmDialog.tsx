import { useT } from '@simple-module-py/i18n';
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
 * Confirm a consequential action (delete/restore/purge) without handing the
 * page to `window.confirm()` — which cannot show a server error if the
 * confirmed action fails, only that the user said yes.
 *
 * The dialog stays open and shows the error on a rejected `onConfirm`, so a
 * delete that comes back `403` or `409` is visible instead of looking like
 * it went through. This is a self-contained copy of the same idea in
 * `pagebuilder/components/ConfirmDialog.tsx` rather than a shared import —
 * modules do not import each other's frontend code.
 */
export function ConfirmDialog({
  trigger,
  title,
  description,
  body,
  confirmLabel,
  cancelLabel,
  pendingLabel,
  destructive = false,
  confirmDisabled = false,
  initialFocusId,
  onOpenChange,
  onConfirm,
}: {
  trigger: ReactNode;
  title: string;
  /** A sentence, rendered inside Radix's `AlertDialogDescription` — a real
   *  `<p>` (L6). Block markup (a list, another paragraph) or anything
   *  focusable nested in here is both invalid HTML and gets read by
   *  `aria-describedby` as though it were the description itself. */
  description: ReactNode;
  /** Extra content — a list of consequences, a confirmation input — rendered
   *  after the description but outside it, so it can be a `<div>`, a `<ul>`,
   *  or hold a focusable control without nesting inside that `<p>` (L6). */
  body?: ReactNode;
  confirmLabel: string;
  /** Default "Cancel" / "Saving…" — what every caller in this module says. */
  cancelLabel?: string;
  pendingLabel?: string;
  destructive?: boolean;
  /** Disables the confirm button without hiding it — for a caller (the
   *  referrer-aware delete dialog) that still wants the reason visible in
   *  `description`/`body` rather than the dialog refusing to open at all. */
  confirmDisabled?: boolean;
  /** U8: the id of a control inside `body` to focus on open, in place of
   *  Radix `AlertDialog`'s own default (the Cancel button — deliberate
   *  there for a plain yes/no, but wrong for a dialog whose whole point is
   *  the input in `body`, such as a typed confirmation). Radix focuses
   *  Cancel via its own `onOpenAutoFocus`, which runs *after* whatever this
   *  passes — `event.preventDefault()` is what keeps it from immediately
   *  taking focus back. */
  initialFocusId?: string;
  /** Fires with the new open state, before anything else in this component
   *  reacts to it — a caller that needs to fetch something to fill in
   *  `description`/`body` starts that fetch here, on open. */
  onOpenChange?: (open: boolean) => void;
  /** Rejecting keeps the dialog open and surfaces the message. */
  onConfirm: () => Promise<unknown>;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = (next: boolean) => {
    if (pending) return;
    setOpen(next);
    if (!next) setError(null);
    onOpenChange?.(next);
  };

  const confirm = async () => {
    setPending(true);
    setError(null);
    try {
      await onConfirm();
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={change}>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent
        onOpenAutoFocus={(event) => {
          if (!initialFocusId) return;
          const el = document.getElementById(initialFocusId);
          if (!el) return;
          event.preventDefault();
          el.focus();
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {body}
        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>
            {cancelLabel ?? t('records.editor.cancel', { defaultValue: 'Cancel' })}
          </AlertDialogCancel>
          <AlertDialogAction
            disabled={pending || confirmDisabled}
            variant={destructive ? 'destructive' : 'default'}
            onClick={(e) => {
              e.preventDefault();
              void confirm();
            }}
          >
            {pending
              ? (pendingLabel ?? t('records.editor.saving', { defaultValue: 'Saving…' }))
              : confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
