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
import { FieldError } from '@simple-module-py/ui/components/ui/field';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { type FormEvent, useId, useState } from 'react';
import { useFormErrors } from '../../hooks/useFormErrors';
import { createCalendar, updateCalendar } from '../../utils/api';
import { fieldErrorId, invalidProps, requiredText } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';
import {
  type Calendar,
  type CalendarInput,
  DEFAULT_COLOR,
  VISIBILITIES,
  type Visibility,
} from '../../utils/types';

/** The 422 paths this form has an input (and a message line) for. */
const SHOWN = ['name', 'slug', 'color', 'description', 'default_timezone'] as const;

export function CalendarDialog({
  calendar,
  defaultTimezone,
  onSaved,
  onGone,
}: {
  calendar?: Calendar;
  defaultTimezone: string;
  onSaved: () => void;
  /** The calendar was trashed or deleted elsewhere: refresh the list. */
  onGone?: () => void;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant={calendar ? 'outline' : 'default'}
          aria-label={
            calendar ? t(keys.events.calendars.edit_for, { name: calendar.name }) : undefined
          }
        >
          {t(calendar ? keys.events.common.edit : keys.events.calendars.new)}
        </Button>
      </DialogTrigger>
      {open && (
        <CalendarForm
          calendar={calendar}
          defaultTimezone={defaultTimezone}
          onGone={onGone}
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
  onGone,
}: {
  calendar?: Calendar;
  defaultTimezone: string;
  onSaved: () => void;
  onGone?: () => void;
}) {
  const { t } = useT();
  const copy = keys.events.calendars;
  const zoneList = useId();
  const [name, setName] = useState(calendar?.name ?? '');
  const [slug, setSlug] = useState(calendar?.slug ?? '');
  const [color, setColor] = useState(calendar?.color ?? DEFAULT_COLOR);
  const [description, setDescription] = useState(calendar?.description ?? '');
  const [timezone, setTimezone] = useState(calendar?.default_timezone ?? defaultTimezone);
  const [visibility, setVisibility] = useState<Visibility>('private');
  const [pending, setPending] = useState(false);
  const errors = useFormErrors(keys.events.errors.calendar_gone, onGone, SHOWN);
  const [zones] = useState(() => new Set(['UTC', ...Intl.supportedValuesOf('timeZone')]));
  async function save(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    errors.reset();
    const found: Record<string, string> = {};
    if (!name.trim()) found.name = requiredText();
    // The list below is only a suggestion: the server decides what a zone is.
    if (!timezone.trim()) found.default_timezone = requiredText();
    if (Object.keys(found).length > 0) {
      errors.reject(found);
      return;
    }
    setPending(true);
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
      errors.fail(e);
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
      <form ref={errors.formRef} className="grid gap-4" noValidate onSubmit={save}>
        <div className="grid gap-2">
          <Label htmlFor="calendar-name">{t(copy.name)}</Label>
          <Input
            id="calendar-name"
            required
            maxLength={200}
            value={name}
            {...invalidProps('calendar-name', errors.fields.name)}
            onChange={(e) => {
              setName(e.target.value);
              errors.clearField('name');
            }}
          />
          <FieldError id={fieldErrorId('calendar-name')}>{errors.fields.name}</FieldError>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="calendar-slug">{t(copy.slug)}</Label>
          <Input
            id="calendar-slug"
            maxLength={80}
            pattern="[a-z0-9]+(-[a-z0-9]+)*"
            value={slug}
            {...invalidProps('calendar-slug', errors.fields.slug)}
            onChange={(e) => {
              setSlug(e.target.value);
              errors.clearField('slug');
            }}
          />
          <FieldError id={fieldErrorId('calendar-slug')}>{errors.fields.slug}</FieldError>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="calendar-color">{t(copy.color)}</Label>
          <Input
            id="calendar-color"
            type="color"
            value={color}
            {...invalidProps('calendar-color', errors.fields.color)}
            onChange={(e) => {
              setColor(e.target.value);
              errors.clearField('color');
            }}
          />
          <FieldError id={fieldErrorId('calendar-color')}>{errors.fields.color}</FieldError>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="calendar-description">{t(copy.description)}</Label>
          <Textarea
            id="calendar-description"
            maxLength={2000}
            value={description}
            {...invalidProps('calendar-description', errors.fields.description)}
            onChange={(e) => {
              setDescription(e.target.value);
              errors.clearField('description');
            }}
          />
          <FieldError id={fieldErrorId('calendar-description')}>
            {errors.fields.description}
          </FieldError>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="calendar-timezone">{t(copy.timezone)}</Label>
          <Input
            id="calendar-timezone"
            required
            maxLength={64}
            list={zoneList}
            value={timezone}
            {...invalidProps('calendar-timezone', errors.fields.default_timezone)}
            onChange={(e) => {
              setTimezone(e.target.value);
              errors.clearField('default_timezone');
            }}
          />
          <FieldError id={fieldErrorId('calendar-timezone')}>
            {errors.fields.default_timezone}
          </FieldError>
          <datalist id={zoneList}>
            {[...zones].map((zone) => (
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
              {VISIBILITIES.map((v) => (
                <option key={v} value={v}>
                  {t(keys.events.visibility[v])}
                </option>
              ))}
            </NativeSelect>
          </div>
        )}
        {errors.error && (
          <p role="alert" className="text-destructive">
            {errors.error}
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
