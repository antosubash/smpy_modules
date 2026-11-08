/** Lift one suppression, audited: the address typed again and a note (G12).
 *
 *  A hard bounce never pre-fills the address, so lifting means typing it. The
 *  `version` posted is the one of the row the dialog was opened on (C3): a row
 *  that changed meanwhile is refused with `suppression_changed`, and the dialog
 *  then closes and hands the message to `onStale`, since every retry from it
 *  would post the same stale version. */

import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@simple-module-py/ui/components/ui/dialog';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { useEffect, useState } from 'react';

import { api, errorMessage } from '../../utils/api';
import { isCode } from '../../utils/http';
import { keys, useT } from '../../utils/i18n';
import type { Suppression } from '../../utils/types';

const copy = keys.newsletter.suppressions.lift;
const MAX_NOTE = 500;

interface Props {
  suppression: Suppression;
  /** The address the caller already knows (a subscriber's own); never used for a hard bounce. */
  knownEmail?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onLifted: () => void;
  /** The row changed under the dialog (`suppression_changed`): the dialog closes;
   *  show `message` and reload the list. */
  onStale?: (message: string) => void;
}

const initialEmail = (s: Suppression, known?: string) =>
  s.reason === 'hard_bounce' ? '' : (known ?? '');

export function LiftDialog({
  suppression,
  knownEmail,
  open,
  onOpenChange,
  onLifted,
  onStale,
}: Props) {
  const { t } = useT();
  const [email, setEmail] = useState(() => initialEmail(suppression, knownEmail));
  const [note, setNote] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setEmail(initialEmail(suppression, knownEmail));
    setNote('');
    setError(null);
  }, [open, suppression, knownEmail]);

  const ready = email.trim() !== '' && note.trim() !== '' && !pending;

  const confirm = async () => {
    setPending(true);
    setError(null);
    try {
      await api.liftSuppression(suppression.id, {
        version: suppression.version,
        email: email.trim(),
        note: note.trim(),
      });
      onLifted();
      onOpenChange(false);
    } catch (e) {
      const message = errorMessage(e, t);
      if (isCode(e, 'suppression_changed')) {
        onStale?.(message);
        onOpenChange(false);
      } else {
        setError(message);
      }
    } finally {
      setPending(false);
    }
  };

  const warning =
    suppression.reason === 'hard_bounce'
      ? { text: copy.hard_bounce_warning, destructive: false }
      : suppression.reason === 'unsubscribed'
        ? { text: copy.opt_out_warning, destructive: true }
        : { text: copy.cleaned_hint, destructive: false };

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (ready) void confirm();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t(copy.title)}</DialogTitle>
            <DialogDescription>{suppression.fingerprint}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 py-4">
            <p
              role={warning.destructive ? 'alert' : undefined}
              className={
                warning.destructive
                  ? 'rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive'
                  : 'text-sm text-muted-foreground'
              }
            >
              {t(warning.text)}
            </p>
            <Label htmlFor="newsletter-lift-email">{t(copy.email_label)}</Label>
            <Input
              id="newsletter-lift-email"
              type="email"
              autoComplete="off"
              value={email}
              maxLength={320}
              disabled={pending}
              onChange={(e) => setEmail(e.target.value)}
            />
            <Label htmlFor="newsletter-lift-note">{t(copy.note_label)}</Label>
            <Textarea
              id="newsletter-lift-note"
              value={note}
              maxLength={MAX_NOTE}
              disabled={pending}
              onChange={(e) => setNote(e.target.value)}
            />
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => onOpenChange(false)}
            >
              {t(copy.cancel)}
            </Button>
            <Button type="submit" disabled={!ready}>
              {t(copy.confirm)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
