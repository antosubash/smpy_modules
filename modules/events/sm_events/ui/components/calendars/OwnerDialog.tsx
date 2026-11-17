import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@simple-module-py/ui/components/ui/dialog';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { type FormEvent, useState } from 'react';
import { MIN_QUERY, useCandidates } from '../../hooks/useCandidates';
import { errorText, isGone, transferOwner } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import { Name, withName } from '../../utils/isolate';
import type { ShareCandidate } from '../../utils/types';

export function OwnerDialog({
  calendarId,
  calendarName,
  onSaved,
}: {
  calendarId: string;
  calendarName: string;
  onSaved: () => void;
}) {
  const { t } = useT();
  const copy = keys.events.calendars;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<ShareCandidate | null>(null);
  const search = useCandidates(calendarId, open, query, onSaved);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!selected || pending) return;
    setPending(true);
    setError(null);
    try {
      await transferOwner(calendarId, selected.id);
      onSaved();
      setOpen(false);
    } catch (e) {
      setError(errorText(e, keys.events.errors.calendar_gone));
      if (isGone(e)) onSaved();
    } finally {
      setPending(false);
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!pending) {
          setOpen(next);
          setQuery('');
          setSelected(null);
          setError(null);
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" aria-label={t(copy.transfer_for, { name: calendarName })}>
          {t(copy.transfer)}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto" showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{t(copy.transfer)}</DialogTitle>
          <DialogDescription>{t(copy.transfer_description)}</DialogDescription>
        </DialogHeader>
        <form onSubmit={save} noValidate className="grid gap-4">
          <Label htmlFor="owner-search">{t(keys.events.share.search_label)}</Label>
          <Input
            id="owner-search"
            type="search"
            maxLength={100}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelected(null);
            }}
          />
          {search.tooShort ? (
            <p>{t(keys.events.share.search_min, { min: MIN_QUERY })}</p>
          ) : (
            <ul>
              {search.candidates.map((candidate) => (
                <li key={candidate.id} className="flex items-center justify-between gap-2 py-2">
                  <span>
                    <Name>{candidate.display_name}</Name>
                    <span className="block text-muted-foreground">{candidate.email}</span>
                  </span>
                  <Button
                    type="button"
                    variant="outline"
                    aria-pressed={selected?.id === candidate.id}
                    onClick={() => setSelected(candidate)}
                  >
                    {t(copy.select_owner, { name: candidate.display_name })}
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {selected && <p>{withName(t, copy.selected_owner, selected.display_name)}</p>}
          {(error || search.error) && (
            <p role="alert" className="text-destructive">
              {error ?? search.error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button type="button" disabled={pending} variant="outline">
                {t(keys.events.common.cancel)}
              </Button>
            </DialogClose>
            <Button disabled={pending || !selected}>{t(copy.transfer)}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
