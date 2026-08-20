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
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { type ReactNode, useState } from 'react';

import { usePendingDialog } from '../hooks/usePendingDialog';

/** How much a confirmation is allowed to cost the person clicking it.
 *
 * A deliberate scale rather than a style choice: friction has to track blast
 * radius, or people learn to click through the cheap confirmations and then
 * click through the expensive one exactly the same way.
 *
 * - `low` — reversible; nothing is public. A plain button.
 * - `medium` — this screen cannot undo it, but nothing live is lost: either it
 *   changes the public site while the content survives (unpublish), or it
 *   removes something for good that nothing references (an unused asset).
 * - `high` — irreversible past the retention window. Requires typing a phrase.
 *
 * The axis is how hard the result is to walk back, not whether the public site
 * changes. An irreversible delete does not get `low` because it happens to be
 * invisible from outside.
 */
export type ConfirmLevel = 'low' | 'medium' | 'high';

const CONFIRM_PHRASE_INPUT = 'confirm-dialog-phrase';

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
  level,
  confirmPhrase,
  children,
  onConfirm,
}: {
  trigger: ReactNode;
  title: string;
  description: ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
  /** Blast radius. Defaults from `destructive` so existing call sites keep
   *  the behaviour they had before the scale existed. */
  level?: ConfirmLevel;
  /** At `high`, the phrase that must be typed before the action unlocks.
   *  Ignored at the other levels. */
  confirmPhrase?: string;
  /** Extra controls — a reassignment target, a checkbox — above the buttons. */
  children?: ReactNode;
  /** Rejecting keeps the dialog open and surfaces the message. */
  onConfirm: () => Promise<unknown>;
}) {
  const [typed, setTyped] = useState('');

  const resolvedLevel: ConfirmLevel = level ?? (destructive ? 'medium' : 'low');
  // Compared exactly, case included. A forgiving match would defeat the point:
  // the delay is the safeguard, and it only works while the phrase is actually
  // being read off the screen.
  const needsPhrase = resolvedLevel === 'high' && !!confirmPhrase;
  const unlocked = !needsPhrase || typed === confirmPhrase;

  // The open/pending/error lifecycle is shared with NoteDialog — see the hook
  // for the invariants (in-flight request owns the dialog, failure keeps it
  // open, closing clears the error). The `onClose` callback clears the typed
  // phrase, because reopening must not inherit the one typed last time: that
  // would put a second delete one click from confirmed, which is the exact
  // property this level exists to remove.
  const { open, pending, error, change, run } = usePendingDialog(`${confirmLabel} failed`, () =>
    setTyped(''),
  );

  return (
    <AlertDialog open={open} onOpenChange={change}>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {children && <div className="grid gap-2 py-2">{children}</div>}
        {needsPhrase && (
          <div className="grid gap-2 py-2">
            <Label htmlFor={CONFIRM_PHRASE_INPUT}>
              Type <code className="font-mono font-semibold">{confirmPhrase}</code> to confirm
            </Label>
            <Input
              id={CONFIRM_PHRASE_INPUT}
              value={typed}
              autoComplete="off"
              disabled={pending}
              onChange={(e) => setTyped(e.target.value)}
            />
          </div>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={pending || !unlocked}
            className={
              resolvedLevel === 'low' ? '' : 'bg-destructive text-white hover:bg-destructive/90'
            }
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
