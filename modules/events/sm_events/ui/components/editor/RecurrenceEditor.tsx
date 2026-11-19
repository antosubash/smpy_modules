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
import { CustomRule } from './CustomRule';
import { RecurrenceEnd } from './RecurrenceEnd';

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
  onIncomplete,
}: {
  value: string;
  start: string;
  timezone: string;
  disabled: boolean;
  /** Why the rule cannot be edited (sub-events do not repeat). */
  reason?: string;
  error?: string;
  onChange: (rule: string) => void;
  /** True while the end is "on a date" and no date is set: the form cannot be saved. */
  onIncomplete?: (incomplete: boolean) => void;
}) {
  const { t, locale } = useT();
  const copy = keys.events.recurrence;
  const parsed = parseRule(value, start, timezone);
  // Text editing is the user's choice; a stored custom rule is only shown.
  const [editing, setEditing] = useState(false);
  const raw = editing || (parsed !== null && isCustom(parsed));
  // The rule text that stands for "ends on a date" while no date is set yet.
  const [dateless, setDateless] = useState<string | null>(null);
  const untilMissing = dateless !== null && dateless === value;
  useEffect(() => onIncomplete?.(untilMissing), [untilMissing, onIncomplete]);
  const form = parsed && !isCustom(parsed) ? parsed : null;
  const previous = useRef(start);
  // A new start can break a monthly "nth weekday"; weekly gains the new weekday.
  useEffect(() => {
    if (previous.current === start) return;
    previous.current = start;
    if (form) {
      const next = buildRule(fitToStart(form, start), start);
      if (next !== value) {
        if (untilMissing) setDateless(next);
        onChange(next);
      }
    }
  }, [start, form, value, onChange, untilMissing]);

  const apply = (next: RuleForm) => {
    const text = buildRule(fitToStart(next, start), start);
    if (untilMissing) setDateless(text); // the end stays "on a date" while it has none
    onChange(text);
  };
  const mode = raw ? CUSTOM : form ? form.freq : NONE;
  function pick(next: string) {
    setEditing(next === CUSTOM);
    if (next === NONE) onChange('');
    else if (next !== CUSTOM) apply({ ...(form ?? defaultRule()), freq: next as Freq });
  }
  const choices = monthlyChoices(start);
  const weekday = startParts(start).weekday;
  const nthWeekday = weekdayName(weekday, locale);
  const endKind = form && untilMissing ? 'until' : (form?.end.kind ?? 'never');
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
        <CustomRule
          value={value}
          editing={editing}
          onEdit={() => setEditing(true)}
          onChange={(rule) => {
            setEditing(true);
            onChange(rule);
          }}
        />
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
          <RecurrenceEnd
            form={form}
            start={start}
            kind={endKind}
            untilMissing={untilMissing}
            onEnd={(end, dateless) => {
              const next = buildRule(fitToStart({ ...form, end }, start), start);
              setDateless(dateless ? next : null);
              onChange(next);
            }}
          />
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
