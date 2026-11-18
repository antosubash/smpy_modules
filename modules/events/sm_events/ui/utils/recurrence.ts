/** The recurrence editor's model: a small subset of RRULE that a form can show,
 *  and the text the server stores (`sm_events/calendar/rrule.py` is the judge).
 *  A stored rule outside the subset is `{ custom }` and is edited as raw text. */
import { keys, translate as t } from './i18n';

export const WEEKDAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'] as const;
export type Weekday = (typeof WEEKDAYS)[number];
export const FREQS = ['DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'] as const;
export type Freq = (typeof FREQS)[number];
export type Nth = -1 | 1 | 2 | 3 | 4;
export type RuleEnd =
  | { kind: 'never' }
  | { kind: 'count'; count: number }
  | { kind: 'until'; date: string };
export type RuleForm = {
  freq: Freq;
  interval: number;
  byDay: Weekday[];
  monthly: { mode: 'day' | 'nth'; nth?: Nth };
  end: RuleEnd;
};
export type Custom = { custom: string };
export const isCustom = (rule: RuleForm | Custom): rule is Custom => 'custom' in rule;

/** Mirrors `RRULE_MAX_INTERVAL`, `RRULE_MAX_COUNT` and `RRULE_MAX_LEN` in
 *  `sm_events/core/constants/__init__.py`; `recurrence.test.ts` reads that file and fails on a mismatch. */
export const INTERVAL_MAX = 99;
export const COUNT_MAX = 730;
export const RRULE_MAX_LEN = 500;

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const DAY = /^(\d{4})-(\d{2})-(\d{2})/;

export function startParts(start: string): {
  year: number;
  month: number;
  day: number;
  weekday: Weekday;
} {
  const [, y = '1970', m = '01', d = '01'] = DAY.exec(start) ?? [];
  const [year, month, day] = [Number(y), Number(m), Number(d)];
  const index = (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7;
  return { year, month, day, weekday: WEEKDAYS[index] ?? 'MO' };
}

/** Which monthly patterns the start date satisfies: the day of the month, the
 *  nth weekday (1 to 4) and the last weekday. A rule the start does not match
 *  is refused by the server (`start_not_in_rule`). */
export function monthlyChoices(start: string): {
  day: number;
  nth: Nth | undefined;
  last: boolean;
} {
  const { year, month, day } = startParts(start);
  const length = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const ordinal = Math.ceil(day / 7);
  return { day, nth: ordinal <= 4 ? (ordinal as Nth) : undefined, last: day + 7 > length };
}

/** The form with any monthly pattern the start no longer satisfies reset to "day". */
export function fitToStart(form: RuleForm, start: string): RuleForm {
  if (form.freq !== 'MONTHLY' || form.monthly.mode !== 'nth') return form;
  const choices = monthlyChoices(start);
  const ok = form.monthly.nth === -1 ? choices.last : form.monthly.nth === choices.nth;
  return ok ? form : { ...form, monthly: { mode: 'day' } };
}

function localDate(instant: Date, timezone?: string): string {
  if (!timezone) return instant.toISOString().slice(0, 10);
  try {
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: timezone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).format(instant);
  } catch {
    return instant.toISOString().slice(0, 10);
  }
}

function parseUntil(value: string, timezone?: string): string | null {
  const date = /^(\d{4})(\d{2})(\d{2})$/.exec(value);
  if (date) return `${date[1]}-${date[2]}-${date[3]}`;
  const stamp = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(value);
  if (!stamp) return null;
  const [, y, mo, d, h, mi, s] = stamp.map(Number);
  return localDate(new Date(Date.UTC(y ?? 0, (mo ?? 1) - 1, d ?? 1, h, mi, s)), timezone);
}

const NUMBER = /^\d+$/;
const PLAIN_DAY = /^(MO|TU|WE|TH|FR|SA|SU)$/;
const NTH_DAY = /^(-1|[1-4])(MO|TU|WE|TH|FR|SA|SU)$/;
const KNOWN = new Set(['FREQ', 'INTERVAL', 'COUNT', 'UNTIL', 'BYDAY', 'BYMONTHDAY']);

/** The rule as the form shows it: `null` for no recurrence, `{ custom }` for a
 *  rule the form cannot express. `timezone` turns a stored UTC `UNTIL` into the
 *  event's own date (without it, the UTC date). */
export function parseRule(
  text: string | null,
  start: string,
  timezone?: string,
): RuleForm | Custom | null {
  const raw = text?.trim().replace(/^RRULE:/i, '') ?? '';
  if (!raw) return null;
  const custom = { custom: raw };
  const parts = new Map<string, string>();
  for (const piece of raw.split(';')) {
    const [name = '', value = ''] = piece.split('=');
    const key = name.toUpperCase();
    if (!KNOWN.has(key) || parts.has(key) || !value) return custom;
    parts.set(key, value.toUpperCase());
  }
  const freq = parts.get('FREQ') as Freq | undefined;
  if (!freq || !FREQS.includes(freq)) return custom;
  const interval = parts.get('INTERVAL');
  const count = parts.get('COUNT');
  const until = parts.get('UNTIL');
  if ((interval && !NUMBER.test(interval)) || (count && !NUMBER.test(count))) return custom;
  if (count && until) return custom;
  // A stored number outside what the form offers is never clamped silently.
  if (interval && (Number(interval) < 1 || Number(interval) > INTERVAL_MAX)) return custom;
  if (count && (Number(count) < 1 || Number(count) > COUNT_MAX)) return custom;
  let end: RuleEnd = { kind: 'never' };
  if (count) end = { kind: 'count', count: Number(count) };
  if (until) {
    const date = parseUntil(until, timezone);
    if (!date) return custom;
    end = { kind: 'until', date };
  }
  const byDay = parts.get('BYDAY');
  const byMonthDay = parts.get('BYMONTHDAY');
  const form: RuleForm = {
    freq,
    interval: interval ? Number(interval) : 1,
    byDay: [],
    monthly: { mode: 'day' },
    end,
  };
  const { day, weekday } = startParts(start);
  if (freq === 'WEEKLY') {
    const days = byDay ? byDay.split(',') : [];
    if (byMonthDay || !days.every((d) => PLAIN_DAY.test(d))) return custom;
    form.byDay = WEEKDAYS.filter((d) => days.includes(d));
    return form;
  }
  if (freq === 'MONTHLY') {
    if (byDay && byMonthDay) return custom;
    const nth = byDay ? NTH_DAY.exec(byDay) : null;
    if (nth) {
      if (nth[2] !== weekday) return custom;
      return { ...form, monthly: { mode: 'nth', nth: Number(nth[1]) as Nth } };
    }
    return byDay || (byMonthDay && byMonthDay !== String(day)) ? custom : form;
  }
  return byDay || byMonthDay ? custom : form;
}

/** The rule text for the form on `start`: weekly always carries the start's
 *  weekday, and monthly names its day or weekday from the start, so the start
 *  is always the first occurrence. */
export function buildRule(form: RuleForm, start: string): string {
  const { day, weekday } = startParts(start);
  const parts = [`FREQ=${form.freq}`];
  const interval = Math.min(INTERVAL_MAX, Math.max(1, Math.trunc(form.interval) || 1));
  if (interval > 1) parts.push(`INTERVAL=${interval}`);
  if (form.end.kind === 'count') {
    parts.push(`COUNT=${Math.min(COUNT_MAX, Math.max(1, Math.trunc(form.end.count) || 1))}`);
  }
  // An "on a date" end with no date yet adds nothing: never an empty part.
  if (form.end.kind === 'until' && ISO_DAY.test(form.end.date)) {
    parts.push(`UNTIL=${form.end.date.replaceAll('-', '')}`);
  }
  if (form.freq === 'WEEKLY') {
    const days = new Set<Weekday>([...form.byDay, weekday]);
    parts.push(`BYDAY=${WEEKDAYS.filter((d) => days.has(d)).join(',')}`);
  }
  if (form.freq === 'MONTHLY') {
    parts.push(
      form.monthly.mode === 'nth' && form.monthly.nth
        ? `BYDAY=${form.monthly.nth}${weekday}`
        : `BYMONTHDAY=${day}`,
    );
  }
  return parts.join(';');
}

/** `en` reads day-month-year like the German console does; other locales as they are. */
export const dateLocale = (locale?: string): string | undefined =>
  !locale || locale === 'en' ? 'en-GB' : locale;

export function weekdayName(day: Weekday, locale?: string): string {
  const monday = Date.UTC(2024, 0, 1);
  const at = new Date(monday + WEEKDAYS.indexOf(day) * 86_400_000);
  return new Intl.DateTimeFormat(dateLocale(locale), { weekday: 'long', timeZone: 'UTC' }).format(
    at,
  );
}

const UNIT = {
  DAILY: [keys.events.recurrence.every_day, keys.events.recurrence.every_days],
  WEEKLY: [keys.events.recurrence.every_week, keys.events.recurrence.every_weeks],
  MONTHLY: [keys.events.recurrence.every_month, keys.events.recurrence.every_months],
  YEARLY: [keys.events.recurrence.every_year, keys.events.recurrence.every_years],
} as const;
const ORDINAL = {
  1: keys.events.recurrence.ordinal.first,
  2: keys.events.recurrence.ordinal.second,
  3: keys.events.recurrence.ordinal.third,
  4: keys.events.recurrence.ordinal.fourth,
  '-1': keys.events.recurrence.ordinal.last,
} as const;

/** A sentence for the rule: "Every week on Monday and Wednesday, 10 times". */
export function summarise(rule: RuleForm | Custom, start: string, locale?: string): string {
  if (isCustom(rule)) return t(keys.events.recurrence.custom_summary, { rule: rule.custom });
  const copy = keys.events.recurrence;
  const { day, weekday } = startParts(start);
  const [one, many] = UNIT[rule.freq];
  let text = rule.interval > 1 ? t(many, { count: rule.interval }) : t(one);
  if (rule.freq === 'WEEKLY') {
    const days = new Set<Weekday>([...rule.byDay, weekday]);
    const names = WEEKDAYS.filter((d) => days.has(d)).map((d) => weekdayName(d, locale));
    const list = new Intl.ListFormat(dateLocale(locale), { type: 'conjunction' }).format(names);
    text += t(copy.on_days, { days: list });
  }
  if (rule.freq === 'MONTHLY') {
    text +=
      rule.monthly.mode === 'nth' && rule.monthly.nth
        ? t(copy.on_nth, {
            ordinal: t(ORDINAL[rule.monthly.nth]),
            weekday: weekdayName(weekday, locale),
          })
        : t(copy.on_day, { day });
  }
  if (rule.end.kind === 'count') {
    text += rule.end.count === 1 ? t(copy.end_once) : t(copy.end_times, { count: rule.end.count });
  }
  if (rule.end.kind === 'until') {
    const [y = 1970, m = 1, d = 1] = rule.end.date.split('-').map(Number);
    const date = new Intl.DateTimeFormat(dateLocale(locale), {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      timeZone: 'UTC',
    }).format(new Date(Date.UTC(y, m - 1, d)));
    text += t(copy.end_until, { date });
  }
  return text;
}

export const defaultRule = (): RuleForm => ({
  freq: 'WEEKLY',
  interval: 1,
  byDay: [],
  monthly: { mode: 'day' },
  end: { kind: 'never' },
});
