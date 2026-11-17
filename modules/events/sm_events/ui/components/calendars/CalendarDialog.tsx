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
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { type FormEvent, useId, useState } from 'react';
import { createCalendar, errorText, updateCalendar } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import type { Calendar, CalendarInput, Visibility } from '../../utils/types';

export function CalendarDialog({
  calendar,
  defaultTimezone,
  onSaved,
}: {
  calendar?: Calendar;
  defaultTimezone: string;
  onSaved: () => void;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant={calendar ? 'outline' : 'default'}>
          {t(calendar ? keys.events.common.edit : keys.events.calendars.new)}
        </Button>
      </DialogTrigger>
      {open && (
        <CalendarForm
          calendar={calendar}
          defaultTimezone={defaultTimezone}
          onSaved={() => {
            onSaved();
            setOpen(false);
          }}
        />
      )}
    </Dialog>
  );
}

function CalendarForm({
  calendar,
  defaultTimezone,
  onSaved,
}: {
  calendar?: Calendar;
  defaultTimezone: string;
  onSaved: () => void;
}) {
  const { t } = useT();
  const copy = keys.events.calendars;
  const zoneList = useId();
  const [name, setName] = useState(calendar?.name ?? '');
  const [slug, setSlug] = useState(calendar?.slug ?? '');
  const [color, setColor] = useState(calendar?.color ?? '#2563eb');
  const [description, setDescription] = useState(calendar?.description ?? '');
  const [timezone, setTimezone] = useState(calendar?.default_timezone ?? defaultTimezone);
  const [visibility, setVisibility] = useState<Visibility>('private');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const zones = Intl.supportedValuesOf('timeZone');
  async function save(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    const body: CalendarInput = {
      name,
      color,
      description: description || null,
      default_timezone: timezone,
      ...(slug ? { slug } : {}),
      ...(!calendar ? { visibility } : {}),
    };
    try {
      if (calendar) await updateCalendar(calendar.id, body);
      else await createCalendar(body);
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setPending(false);
    }
  }
  return (
    <DialogContent
      className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
      showCloseButton={false}
      onEscapeKeyDown={(e) => {
        if (pending) e.preventDefault();
      }}
      onInteractOutside={(e) => {
        if (pending) e.preventDefault();
      }}
    >
      <DialogHeader>
        <DialogTitle>{t(calendar ? copy.edit : copy.new)}</DialogTitle>
        <DialogDescription>{t(copy.form_description)}</DialogDescription>
      </DialogHeader>
      <form className="grid gap-4" onSubmit={save}>
        <div className="grid gap-2">
          <Label htmlFor="calendar-name">{t(copy.name)}</Label>
          <Input
            id="calendar-name"
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="calendar-slug">{t(copy.slug)}</Label>
          <Input
            id="calendar-slug"
            maxLength={80}
            pattern="[a-z0-9]+(-[a-z0-9]+)*"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="calendar-color">{t(copy.color)}</Label>
          <Input
            id="calendar-color"
            type="color"
            value={color}
            onChange={(e) => setColor(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="calendar-description">{t(copy.description)}</Label>
          <Textarea
            id="calendar-description"
            maxLength={2000}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="calendar-timezone">{t(copy.timezone)}</Label>
          <Input
            id="calendar-timezone"
            required
            maxLength={64}
            list={zoneList}
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
          />
          <datalist id={zoneList}>
            <option value="UTC" />
            {zones.map((zone) => (
              <option key={zone} value={zone} />
            ))}
          </datalist>
        </div>
        {!calendar && (
          <div className="grid gap-2">
            <Label htmlFor="calendar-visibility">{t(copy.visibility)}</Label>
            <NativeSelect
              id="calendar-visibility"
              value={visibility}
              onChange={(e) => setVisibility(e.target.value as Visibility)}
            >
              {(['private', 'internal', 'public'] as const).map((v) => (
                <option key={v} value={v}>
                  {t(keys.events.visibility[v])}
                </option>
              ))}
            </NativeSelect>
          </div>
        )}
        {error && (
          <p role="alert" className="text-destructive">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <DialogClose asChild>
            <Button type="button" variant="outline" disabled={pending}>
              {t(keys.events.common.cancel)}
            </Button>
          </DialogClose>
          <Button disabled={pending}>
            {t(pending ? keys.events.common.saving : keys.events.common.save)}
          </Button>
        </div>
      </form>
    </DialogContent>
  );
}
