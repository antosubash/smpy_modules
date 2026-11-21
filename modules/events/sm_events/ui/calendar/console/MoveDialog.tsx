/** The keyboard path for every move and resize (the grid's drag has none): a dialog with the
 *  occurrence's start and end on the *event's* own clock, the zone named, and for a series
 *  "only this occurrence / all occurrences". It sends through the same write flow as a drag,
 *  so it gets the same outcomes; a refusal stays here, at its field or as a message. */
import { Link } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@simple-module-py/ui/components/ui/dialog';
import { FieldError } from '@simple-module-py/ui/components/ui/field';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { type FormEvent, useRef, useState } from 'react';
import { useFormErrors } from '../../hooks/useFormErrors';
import { useRequestScope } from '../../hooks/useRequestScope';
import { fieldErrorId, invalidProps, requiredText } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';
import { Name } from '../../utils/isolate';
import { addDays, toInstant, toLocal } from '../time/zones';
import type { Occurrence, OccurrenceChange } from '../types';
import { timeProblems } from './quickCreate';
import { timeErrors } from './timeErrors';
import type { WriteResult } from './useCalendarWrites';
import { isSeries, type Scope } from './writes';

type Props = {
  occurrence: Occurrence | null;
  /** The event's element, which gets focus back when the dialog closes. */
  returnFocus?: HTMLElement | null;
  /** Puts focus back on the occurrence's element, or wherever that element went. */
  restoreFocus?: (occurrence: Occurrence, element: HTMLElement | null) => void;
  onSubmit: (change: OccurrenceChange, scope?: Scope) => Promise<WriteResult>;
  onClose: () => void;
};

export function MoveDialog({ occurrence, returnFocus, restoreFocus, onSubmit, onClose }: Props) {
  // The occurrence outlives the dialog's closing, for the exit animation and the focus.
  const last = useRef(occurrence);
  // The parent clears both when it closes the dialog, before the focus is handed back.
  const lastElement = useRef(returnFocus);
  if (occurrence) {
    last.current = occurrence;
    lastElement.current = returnFocus;
  }
  const shown = occurrence ?? last.current;
  const { t } = useT();
  const copy = keys.events.calendar.move;
  return (
    <Dialog open={occurrence !== null} onOpenChange={(open) => !open && onClose()}>
      {shown && (
        <DialogContent
          className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
          showCloseButton={false}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            document.getElementById('move-start')?.focus();
          }}
          onCloseAutoFocus={(event) => {
            const element = lastElement.current ?? null;
            if (restoreFocus && last.current) {
              event.preventDefault();
              return restoreFocus(last.current, element);
            }
            if (!element?.isConnected) return;
            event.preventDefault();
            element.focus();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t(copy.title)}</DialogTitle>
            <DialogDescription className="dark:text-zinc-400">
              {t(copy.description, { zone: shown.timezone })}
            </DialogDescription>
          </DialogHeader>
          {occurrence && <MoveForm occurrence={occurrence} onSubmit={onSubmit} onClose={onClose} />}
        </DialogContent>
      )}
    </Dialog>
  );
}

function MoveForm({
  occurrence: o,
  onSubmit,
  onClose,
}: Pick<Props, 'onSubmit' | 'onClose'> & { occurrence: Occurrence }) {
  const { t } = useT();
  const copy = keys.events.calendar.move;
  const zone = o.timezone;
  const [start, setStart] = useState(o.all_day ? (o.start_date ?? '') : toLocal(o.start, zone));
  const [end, setEnd] = useState(
    o.all_day ? addDays(o.end_date ?? o.start_date ?? '', -1) : toLocal(o.end, zone),
  );
  const [scope, setScope] = useState<Scope>('one');
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<{ message: string; link?: string } | null>(null);
  const begin = useRequestScope(true);
  const errors = useFormErrors(undefined, undefined, ['times.start', 'times.end']);
  const series = isSeries(o);
  const unchanged =
    start === (o.all_day ? o.start_date : toLocal(o.start, zone)) &&
    end === (o.all_day ? addDays(o.end_date ?? '', -1) : toLocal(o.end, zone));

  async function save(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    errors.reset();
    setNotice(null);
    const found: Record<string, string> = {};
    if (!start) found['times.start'] = requiredText();
    if (!end) found['times.end'] = requiredText();
    if (Object.keys(found).length === 0) {
      Object.assign(found, timeErrors(timeProblems({ allDay: o.all_day, start, end }, zone), t));
    }
    if (Object.keys(found).length > 0) return errors.reject(found);
    if (unchanged) return onClose();
    const change: OccurrenceChange = o.all_day
      ? { occurrence: o, kind: 'reschedule', allDay: true, start, end: addDays(end, 1) }
      : {
          occurrence: o,
          kind: 'reschedule',
          allDay: false,
          start: toInstant(start, zone),
          end: toInstant(end, zone),
        };
    const request = begin();
    setPending(true);
    const result = await onSubmit(change, series ? scope : undefined);
    if (!request.alive()) return;
    setPending(false);
    if (result.ok) return onClose();
    if (result.silent) return;
    if (result.field) errors.reject({ [`times.${result.field}`]: result.message });
    else setNotice({ message: result.message, link: result.link });
  }

  const box = (name: 'start' | 'end', value: string, set: (v: string) => void, label: string) => {
    const id = `move-${name}`;
    const message = errors.fields[`times.${name}`];
    return (
      <div className="grid gap-2">
        <Label htmlFor={id}>{label}</Label>
        <Input
          id={id}
          type={o.all_day ? 'date' : 'datetime-local'}
          required
          value={value}
          {...invalidProps(id, message)}
          onChange={(e) => {
            set(e.target.value);
            errors.clearField(`times.${name}`);
          }}
        />
        <FieldError id={fieldErrorId(id)}>{message}</FieldError>
      </div>
    );
  };
  return (
    <form ref={errors.formRef} noValidate className="grid gap-4" onSubmit={save}>
      <p className="text-sm font-medium">
        <Name>{o.title}</Name>
      </p>
      <div className="grid gap-4 sm:grid-cols-2">
        {box('start', start, setStart, t(copy.start))}
        {box('end', end, setEnd, t(o.all_day ? copy.last_day : copy.end))}
      </div>
      {series && (
        <fieldset className="grid gap-2">
          <legend className="mb-1 text-sm font-medium">{t(copy.scope)}</legend>
          {(['one', 'all'] as const).map((choice) => (
            <label key={choice} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="move-scope"
                value={choice}
                checked={scope === choice}
                onChange={() => setScope(choice)}
              />
              {t(keys.events.calendar.scope[choice])}
            </label>
          ))}
        </fieldset>
      )}
      {notice && (
        <p role="alert" className="text-sm text-destructive dark:text-red-400">
          {notice.message}{' '}
          {notice.link && (
            <Link className="underline" href={notice.link}>
              {t(keys.events.calendar.writes.open_editor)}
            </Link>
          )}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onClose}>
          {t(keys.events.common.cancel)}
        </Button>
        <Button type="submit" disabled={pending}>
          {t(pending ? keys.events.common.saving : copy.submit)}
        </Button>
      </div>
    </form>
  );
}
