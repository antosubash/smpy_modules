import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@simple-module-py/ui/components/ui/dialog';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { type ReactNode, useId, useState } from 'react';

/**
 * Collect a note — a rejection reason, a publish message — before running an
 * action.
 *
 * `window.prompt` gives a single-line box for what is usually a sentence or
 * two of prose to another author, no way to mark the note required, and no
 * way to show the request failing afterwards. It also conflates "cancelled"
 * with "left blank": both come back falsy, so an optional note and an aborted
 * action are indistinguishable without comparing against `null`.
 */
export function NoteDialog({
  trigger,
  title,
  description,
  label,
  placeholder,
  submitLabel,
  required = false,
  destructive = false,
  onSubmit,
}: {
  trigger: ReactNode;
  title: string;
  description: ReactNode;
  label: string;
  placeholder?: string;
  submitLabel: string;
  /** Blocks submit until the note is non-empty. */
  required?: boolean;
  destructive?: boolean;
  /** Rejecting keeps the dialog open and surfaces the message. */
  onSubmit: (note: string) => Promise<unknown>;
}) {
  const fieldId = useId();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = (next: boolean) => {
    if (pending) return;
    setOpen(next);
    if (!next) {
      setNote('');
      setError(null);
    }
  };

  const submit = async () => {
    const trimmed = note.trim();
    if (required && !trimmed) return;
    setPending(true);
    setError(null);
    try {
      await onSubmit(trimmed);
      change(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : `${submitLabel} failed`);
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={change}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!pending) void submit();
          }}
        >
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2 py-4">
            <Label htmlFor={fieldId}>
              {label}
              {!required && <span className="ml-1 text-muted-foreground">(optional)</span>}
            </Label>
            <Textarea
              id={fieldId}
              rows={3}
              value={note}
              autoFocus
              disabled={pending}
              placeholder={placeholder}
              onChange={(e) => setNote(e.target.value)}
            />
            {error && <p className="text-sm text-destructive">{error}</p>}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => change(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant={destructive ? 'destructive' : 'default'}
              disabled={pending || (required && !note.trim())}
            >
              {pending ? 'Working…' : submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
