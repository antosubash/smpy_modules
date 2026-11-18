import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { FieldError } from '@simple-module-py/ui/components/ui/field';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useId, useRef, useState } from 'react';
import { utcOffset } from '../../utils/datetime';
import { clockOf, type FormState, type TimedClock, withAllDay } from '../../utils/event-form';
import { fieldErrorId, invalidProps } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';

type Errors = Record<string, string>;

/** Start, end and timezone on the event's own clock. An all-day event uses
 *  dates, and its end is the last day it covers (inclusive). */
export function TimesFields({
  form,
  errors,
  disabled,
  onChange,
  onEdit,
}: {
  form: FormState;
  errors: Errors;
  disabled: boolean;
  onChange: (next: FormState) => void;
  /** A field was edited: its message is stale. */
  onEdit: (path: string) => void;
}) {
  const { t } = useT();
  const copy = keys.events.editor;
  const zoneList = useId();
  // The clock times before "all day" was ticked, for ticking it off again.
  const remembered = useRef<TimedClock | undefined>(undefined);
  const [zones] = useState(() => new Set(['UTC', ...Intl.supportedValuesOf('timeZone')]));
  const type = form.all_day ? 'date' : 'datetime-local';
  const offset = utcOffset(form.start, form.timezone.trim());
  const set = (patch: Partial<FormState>, path: string) => {
    onChange({ ...form, ...patch });
    onEdit(path);
  };
  const box = (id: string, name: 'start' | 'end', label: string) => (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        required
        disabled={disabled}
        value={form[name]}
        {...invalidProps(id, errors[`times.${name}`])}
        onChange={(e) => set({ [name]: e.target.value }, `times.${name}`)}
      />
      <FieldError id={fieldErrorId(id)}>{errors[`times.${name}`]}</FieldError>
    </div>
  );
  return (
    <fieldset className="grid gap-4" disabled={disabled}>
      <legend className="mb-2 text-sm font-medium">{t(copy.when)}</legend>
      <div className="flex items-center gap-2">
        <Checkbox
          id="event-all-day"
          checked={form.all_day}
          onCheckedChange={(on) => {
            remembered.current = clockOf(form) ?? remembered.current;
            onChange(withAllDay(form, on === true, remembered.current));
          }}
        />
        <Label htmlFor="event-all-day">{t(copy.all_day)}</Label>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {box('event-start', 'start', t(copy.start))}
        {box('event-end', 'end', t(form.all_day ? copy.last_day : copy.end))}
      </div>
      <div className="grid gap-2">
        <Label htmlFor="event-timezone">{t(copy.timezone)}</Label>
        <Input
          id="event-timezone"
          required
          maxLength={64}
          list={zoneList}
          value={form.timezone}
          {...invalidProps('event-timezone', errors['times.timezone'])}
          onChange={(e) => set({ timezone: e.target.value }, 'times.timezone')}
        />
        <FieldError id={fieldErrorId('event-timezone')}>{errors['times.timezone']}</FieldError>
        <datalist id={zoneList}>
          {[...zones].map((zone) => (
            <option key={zone} value={zone} />
          ))}
        </datalist>
        <p className="text-sm text-muted-foreground">
          {offset
            ? t(copy.clock_note, { timezone: form.timezone, offset })
            : t(copy.clock_note_plain, { timezone: form.timezone })}
        </p>
      </div>
    </fieldset>
  );
}
