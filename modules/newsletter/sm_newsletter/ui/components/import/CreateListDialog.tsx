/** "New list": a name and a key (derived from the name until edited), then `POST /lists`. */

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
import { type RefObject, useEffect, useRef, useState } from 'react';

import { errorMessage } from '../../utils/http';
import { keys, useT } from '../../utils/i18n';
import { createList } from '../../utils/importApi';

const copy = keys.newsletter.import.new_list_dialog;
const KEY_ID = 'newsletter-import-list-key';
const LABEL_ID = 'newsletter-import-list-label';
const MAX_LEN = 64;
const KEY_PATTERN = /^[a-z][a-z0-9_]*$/;

/** `Spring Sale 2026!` -> `spring_sale_2026`: records' key pattern, `[a-z][a-z0-9_]*`. */
export function slugify(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^[^a-z]+/, '')
    .replace(/_+$/, '')
    .slice(0, MAX_LEN);
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The new list's key; the caller selects it and adds it to its options. */
  onCreated: (key: string) => void;
  /** Where focus goes when the dialog closes (the button that opened it). */
  returnFocusTo?: RefObject<HTMLElement | null>;
}

export function CreateListDialog({ open, onOpenChange, onCreated, returnFocusTo }: Props) {
  const { t } = useT();
  const [label, setLabel] = useState('');
  const [key, setKey] = useState('');
  const [edited, setEdited] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitting = useRef(false); // a second submit in the same tick sees `pending` unchanged
  const valid = KEY_PATTERN.test(key) && label.trim() !== '';

  // Kept mounted so closing returns focus to the trigger; each opening starts empty.
  useEffect(() => {
    if (!open) return;
    setLabel('');
    setKey('');
    setEdited(false);
    setError(null);
  }, [open]);

  const create = async () => {
    if (submitting.current) return;
    submitting.current = true;
    setPending(true);
    setError(null);
    try {
      const created = await createList(key, label.trim());
      onCreated(created.key);
      onOpenChange(false);
    } catch (e) {
      setError(errorMessage(e, t));
    } finally {
      submitting.current = false;
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent
        onCloseAutoFocus={(e) => {
          if (!returnFocusTo?.current) return;
          e.preventDefault();
          returnFocusTo.current.focus();
        }}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (valid && !pending) void create();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t(copy.title)}</DialogTitle>
            <DialogDescription>{t(copy.key_hint)}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor={LABEL_ID}>{t(copy.label)}</Label>
              <Input
                id={LABEL_ID}
                value={label}
                disabled={pending}
                maxLength={200}
                onChange={(e) => {
                  setLabel(e.target.value);
                  setError(null);
                  if (!edited) setKey(slugify(e.target.value));
                }}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor={KEY_ID}>{t(copy.key)}</Label>
              <Input
                id={KEY_ID}
                value={key}
                disabled={pending}
                maxLength={MAX_LEN}
                onChange={(e) => {
                  setEdited(true);
                  setError(null);
                  setKey(e.target.value);
                }}
              />
            </div>
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
            <Button type="submit" disabled={!valid || pending}>
              {pending ? t(copy.creating) : t(copy.create)}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
