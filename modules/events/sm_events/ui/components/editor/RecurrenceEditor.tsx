import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { FieldError } from '@simple-module-py/ui/components/ui/field';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useEffect, useRef, useState } from 'react';
import { fieldErrorId, invalidProps } from '../../utils/field-errors';
import { keys, useT } from '../../utils/i18n';
import {
  buildRule,
  COUNT_MAX,
  defaultRule,
  FREQS,
  type Freq,
  fitToStart,
  INTERVAL_MAX,
  isCustom,
  monthlyChoices,
  parseRule,
  type RuleForm,
  startParts,
  summarise,
  WEEKDAYS,
  weekdayName,
} from '../../utils/recurrence';

const MODE = 'event-rrule-mode';
const CUSTOM = 'custom';
const NONE = '';

/** The repeat rule as a form: daily, weekly (weekdays), monthly (day of month or
 *  nth weekday) and yearly, ending never, after N times or on a date. A stored
 *  rule outside that is shown as raw text, which the server validates. The rule
 *  text is the value; every change rebuilds it so the start stays its first
 *  occurrence. */
export function RecurrenceEditor({
  value,
  start,
  timezone,
  disabled,
  reason,
  error,
  onChange,
}: {
  value: string;
  start: string;
  timezone: string;
  disabled: boolean;
  /** Why the rule cannot be edited (sub-events do not repeat). */
  reason?: string;
  error?: string;
  onChange: (rule: string) => void;
}) {
  const { t, locale } = useT();
  const copy = keys.events.recurrence;
  const parsed = parseRule(value, start, timezone);
  const [raw, setRaw] = useState(parsed !== null && isCustom(parsed));
  const form = parsed && !isCustom(parsed) ? parsed : null;
  const previous = useRef(start);
  // A new start can break a monthly "nth weekday"; weekly gains the new weekday.
  useEffect(() => {
    if (previous.current === start) return;
    previous.current = start;
    if (form) {
      const next = buildRule(fitToStart(form, start), start);
      if (next !== value) onChange(next);
    }
  }, [start, form, value, onChange]);

  const apply = (next: RuleForm) => onChange(buildRule(fitToStart(next, start), start));
  const mode = raw ? CUSTOM : form ? form.freq : NONE;
  function pick(next: string) {
    setRaw(next === CUSTOM);
    if (next === NONE) onChange('');
    else if (next !== CUSTOM) apply({ ...(form ?? defaultRule()), freq: next as Freq });
  }
  const choices = monthlyChoices(start);
  const weekday = startParts(start).weekday;
  const nthWeekday = weekdayName(weekday, locale);
  const unit = form ? t(copy[`interval_unit_${form.freq.toLowerCase() as 'daily'}`]) : '';
  return (
    <fieldset className="grid gap-3" disabled={disabled}>
      <legend className="mb-2 text-sm font-medium">{t(copy.title)}</legend>
      {reason && <p className="text-sm text-muted-foreground">{reason}</p>}
      <div className="grid gap-2">
        <Label htmlFor={MODE}>{t(copy.frequency)}</Label>
        <NativeSelect
          id={MODE}
          value={mode}
          {...invalidProps(MODE, error)}
          onChange={(e) => pick(e.target.value)}
        >
          <option value={NONE}>{t(copy.none)}</option>
          {FREQS.map((f) => (
            <option key={f} value={f}>
              {t(copy[`freq_${f.toLowerCase()}` as 'freq_daily'])}
            </option>
          ))}
          <option value={CUSTOM}>{t(copy.custom)}</option>
        </NativeSelect>
        <FieldError id={fieldErrorId(MODE)}>{error}</FieldError>
      </div>
      {raw && (
        <div className="grid gap-2">
          <Label htmlFor="event-rrule-text">{t(copy.custom)}</Label>
          <Input
            id="event-rrule-text"
            className="font-mono"
            maxLength={1000}
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
          <p className="text-sm text-muted-foreground">{t(copy.custom_hint)}</p>
        </div>
      )}
      {form && !raw && (
        <>
          <div className="flex items-center gap-2">
            <Label htmlFor="event-rrule-interval">{t(copy.interval)}</Label>
            <Input
              id="event-rrule-interval"
              type="number"
              min={1}
              max={INTERVAL_MAX}
              className="w-20"
              value={form.interval}
              onChange={(e) => apply({ ...form, interval: Number(e.target.value) || 1 })}
            />
            <span>{unit}</span>
          </div>
          {form.freq === 'WEEKLY' && (
            <fieldset className="flex flex-wrap gap-3">
              <legend className="mb-1 text-sm">{t(copy.weekdays)}</legend>
              {WEEKDAYS.map((day) => {
                const own = day === weekday;
                const id = `event-rrule-day-${day}`;
                return (
                  <div key={day} className="flex items-center gap-1">
                    <Checkbox
                      id={id}
                      checked={own || form.byDay.includes(day)}
                      disabled={own}
                      onCheckedChange={(on) =>
                        apply({
                          ...form,
                          byDay:
                            on === true
                              ? [...form.byDay, day]
                              : form.byDay.filter((d) => d !== day),
                        })
                      }
                    />
                    <Label htmlFor={id}>{weekdayName(day, locale)}</Label>
                  </div>
                );
              })}
            </fieldset>
          )}
          {form.freq === 'MONTHLY' && (
            <div className="grid gap-2">
              <Label htmlFor="event-rrule-monthly">{t(copy.monthly_pattern)}</Label>
              <NativeSelect
                id="event-rrule-monthly"
                value={form.monthly.mode === 'day' ? 'day' : String(form.monthly.nth)}
                onChange={(e) =>
                  apply({
                    ...form,
                    monthly:
                      e.target.value === 'day'
                        ? { mode: 'day' }
                        : { mode: 'nth', nth: Number(e.target.value) as -1 | 1 | 2 | 3 | 4 },
                  })
                }
              >
                <option value="day">{t(copy.monthly_day, { day: choices.day })}</option>
                {choices.nth && (
                  <option value={String(choices.nth)}>
                    {t(copy.monthly_nth, {
                      ordinal: t(
                        [
                          '',
                          copy.ordinal.first,
                          copy.ordinal.second,
                          copy.ordinal.third,
                          copy.ordinal.fourth,
                        ][choices.nth] ?? '',
                      ),
                      weekday: nthWeekday,
                    })}
                  </option>
                )}
                {choices.last && (
                  <option value="-1">{t(copy.monthly_last, { weekday: nthWeekday })}</option>
                )}
              </NativeSelect>
            </div>
          )}
          <div className="flex flex-wrap items-end gap-3">
            <div className="grid gap-2">
              <Label htmlFor="event-rrule-end">{t(copy.ends)}</Label>
              <NativeSelect
                id="event-rrule-end"
                value={form.end.kind}
                onChange={(e) => {
                  const kind = e.target.value;
                  apply({
                    ...form,
                    end:
                      kind === 'count'
                        ? { kind: 'count', count: 10 }
                        : kind === 'until'
                          ? { kind: 'until', date: start.slice(0, 10) }
                          : { kind: 'never' },
                  });
                }}
              >
                <option value="never">{t(copy.end_never)}</option>
                <option value="count">{t(copy.end_count)}</option>
                <option value="until">{t(copy.end_date)}</option>
              </NativeSelect>
            </div>
            {form.end.kind === 'count' && (
              <div className="grid gap-2">
                <Label htmlFor="event-rrule-count">{t(copy.count)}</Label>
                <Input
                  id="event-rrule-count"
                  type="number"
                  min={1}
                  max={COUNT_MAX}
                  className="w-24"
                  value={form.end.count}
                  onChange={(e) =>
                    apply({ ...form, end: { kind: 'count', count: Number(e.target.value) || 1 } })
                  }
                />
              </div>
            )}
            {form.end.kind === 'until' && (
              <div className="grid gap-2">
                <Label htmlFor="event-rrule-until">{t(copy.until)}</Label>
                <Input
                  id="event-rrule-until"
                  type="date"
                  value={form.end.date}
                  onChange={(e) => apply({ ...form, end: { kind: 'until', date: e.target.value } })}
                />
              </div>
            )}
          </div>
        </>
      )}
      {parsed && !raw && (
        <p className="text-sm" aria-live="polite">
          {summarise(parsed, start, locale)}
        </p>
      )}
    </fieldset>
  );
}
