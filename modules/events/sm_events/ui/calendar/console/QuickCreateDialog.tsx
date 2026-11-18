/** Create an event from a click or a drag on the grid: a title, a calendar, when, and "More
 *  options" into the full editor. The times are wall clock in the *chosen calendar's* zone,
 *  which the grid's may not be, so the zone is named beside them. */
import { Link } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
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
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { type FormEvent, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { useFormErrors } from '../../hooks/useFormErrors';
import { useRequestScope } from '../../hooks/useRequestScope';
import { createEvent } from '../../utils/api-events';
import { codeFieldPath, fieldErrorId, invalidProps, requiredText } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';
import type { CalendarInfo, CreateSlot } from '../types';
import {
  type Clock,
  clockOf,
  createBody,
  editorHref,
  reexpress,
  timeProblems,
  withAllDay,
} from './quickCreate';
import { timeErrors } from './timeErrors';

type Props = {
  slot: CreateSlot | null;
  calendars: CalendarInfo[];
  /** The calendar shown, when exactly one is. */
  preferred: string | null;
  defaultLocale: string;
  editorUrl: string;
  onCreated: () => void;
  onClose: () => void;
};

export function QuickCreateDialog({ slot, onClose, ...rest }: Props) {
  const { t } = useT();
  const copy = keys.events.calendar.create;
  // Never without a calendar to put the event on: no empty select, no link without an id.
  const open = slot !== null && rest.calendars.some((c) => c.can_write_events);
  return (
    <Dialog open={open} onOpenChange={(open) => !open && onClose()}>
      {slot && open && (
        <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t(copy.title)}</DialogTitle>
            <DialogDescription>{t(copy.description)}</DialogDescription>
          </DialogHeader>
          <QuickCreateForm slot={slot} onClose={onClose} {...rest} />
        </DialogContent>
      )}
    </Dialog>
  );
}

function QuickCreateForm({
  slot,
  calendars,
  preferred,
  defaultLocale,
  editorUrl,
  onCreated,
  onClose,
}: Props & { slot: CreateSlot }) {
  const { t } = useT();
  const copy = keys.events.calendar.create;
  const writable = useMemo(() => calendars.filter((c) => c.can_write_events), [calendars]);
  const first = writable.find((c) => c.id === preferred) ?? writable[0];
  const [calendarId, setCalendarId] = useState(first?.id ?? '');
  const zone = writable.find((c) => c.id === calendarId)?.default_timezone ?? 'UTC';
  const [clock, setClock] = useState<Clock>(() => clockOf(slot, zone));
  const [title, setTitle] = useState('');
  const [pending, setPending] = useState(false);
  const timed = useRef<Clock | undefined>(slot.allDay ? undefined : clock);
  const begin = useRequestScope(true);
  const titlePath = `texts.${defaultLocale}.title`;
  const errors = useFormErrors(
    keys.events.errors.event_gone,
    undefined,
    [titlePath, 'times.start', 'times.end'],
    (e) => codeFieldPath(e, { defaultLocale, slugLocales: [] }),
  );
  const problem = (path: string) => errors.fields[path];

  async function save(event: FormEvent) {
    event.preventDefault();
    if (pending || !first) return;
    errors.reset();
    const found: Record<string, string> = {};
    if (!title.trim()) found[titlePath] = requiredText();
    Object.assign(found, timeErrors(timeProblems(clock, zone), t));
    if (Object.keys(found).length > 0) return errors.reject(found);
    const request = begin();
    setPending(true);
    try {
      await createEvent(createBody(clock, calendarId, zone, defaultLocale, title.trim()));
      toast.success(t(copy.created));
      onCreated();
      if (request.alive()) onClose();
    } catch (e) {
      if (request.alive()) errors.fail(e);
    } finally {
      if (request.alive()) setPending(false);
    }
  }

  const box = (name: 'start' | 'end', label: string) => {
    const id = `quick-${name}`;
    const message = problem(`times.${name}`);
    return (
      <div className="grid gap-2">
        <Label htmlFor={id}>{label}</Label>
        <Input
          id={id}
          type={clock.allDay ? 'date' : 'datetime-local'}
          required
          value={clock[name]}
          {...invalidProps(id, message)}
          onChange={(e) => {
            setClock({ ...clock, [name]: e.target.value });
            errors.clearField(`times.${name}`);
          }}
        />
        <FieldError id={fieldErrorId(id)}>{message}</FieldError>
      </div>
    );
  };
  return (
    <form ref={errors.formRef} noValidate className="grid gap-4" onSubmit={save}>
      <div className="grid gap-2">
        <Label htmlFor="quick-title">{t(copy.title_label)}</Label>
        <Input
          id="quick-title"
          required
          maxLength={300}
          value={title}
          {...invalidProps('quick-title', problem(titlePath))}
          onChange={(e) => {
            setTitle(e.target.value);
            errors.clearField(titlePath);
          }}
        />
        <FieldError id={fieldErrorId('quick-title')}>{problem(titlePath)}</FieldError>
      </div>
      <div className="grid gap-2">
        <Label htmlFor="quick-calendar">{t(copy.calendar)}</Label>
        <NativeSelect
          id="quick-calendar"
          value={calendarId}
          onChange={(e) => {
            const next = writable.find((c) => c.id === e.target.value);
            if (!next) return;
            setClock(reexpress(clock, zone, next.default_timezone));
            setCalendarId(next.id);
          }}
        >
          {writable.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </NativeSelect>
      </div>
      <div className="flex items-center gap-2">
        <Checkbox
          id="quick-all-day"
          checked={clock.allDay}
          onCheckedChange={(on) => {
            if (!clock.allDay) timed.current = clock;
            setClock(withAllDay(clock, on === true, timed.current));
          }}
        />
        <Label htmlFor="quick-all-day">{t(copy.all_day)}</Label>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {box('start', t(copy.start))}
        {box('end', t(clock.allDay ? copy.last_day : copy.end))}
      </div>
      <p className="text-sm text-muted-foreground">{t(copy.zone_note, { zone })}</p>
      {errors.error && (
        <p role="alert" className="text-sm text-destructive">
          {errors.error}
        </p>
      )}
      <div className="flex flex-wrap justify-between gap-2">
        <Button asChild variant="outline">
          <Link href={editorHref(editorUrl, calendarId, clock, title)}>{t(copy.more_options)}</Link>
        </Button>
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            {t(keys.events.common.cancel)}
          </Button>
          <Button type="submit" disabled={pending || !first}>
            {t(pending ? keys.events.common.saving : copy.create)}
          </Button>
        </div>
      </div>
    </form>
  );
}
