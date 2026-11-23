/** The editor's form state, and its conversion to and from the API's bodies.
 *  Times stay on the event's own wall clock (`YYYY-MM-DDTHH:MM`, or a date all
 *  day): the browser never converts to UTC or to another zone. */

import {
  blankRegistration,
  fromRegistration,
  type RegistrationForm,
  toRegistration,
} from './registration-form';
import type {
  AttendanceMode,
  EventCreate,
  EventDetail,
  EventFields,
  EventPatch,
  TextInput,
  TimesInput,
} from './types-events';
import { todayIn } from './zones';

export type TextForm = {
  present: boolean;
  title: string;
  slug: string;
  summary: string;
  description: string;
  seo_title: string;
  seo_description: string;
  noindex: boolean;
};
export type FormState = {
  all_day: boolean;
  timezone: string;
  start: string;
  end: string;
  rrule: string;
  cancelled: boolean;
  attendance_mode: AttendanceMode;
  venue_name: string;
  address: string;
  online_url: string;
  latitude: string;
  longitude: string;
  category_id: string;
  organiser: string;
  image: string;
  registration: RegistrationForm;
  /** The event's type (fixed after create) and its plugin-owned `extra`. */
  type: string;
  extra: Record<string, unknown>;
  texts: Record<string, TextForm>;
};

export const blankText = (present = false): TextForm => ({
  present,
  title: '',
  slug: '',
  summary: '',
  description: '',
  seo_title: '',
  seo_description: '',
  noindex: false,
});

/** Today's date on the clock of `timezone` (the calendar's own, not the browser's). */
export const today = (timezone?: string, now: Date = new Date()): string => todayIn(timezone, now);

export function emptyForm(timezone: string, locales: readonly string[], now?: Date): FormState {
  const day = today(timezone, now);
  return {
    all_day: false,
    timezone,
    start: `${day}T09:00`,
    end: `${day}T10:00`,
    rrule: '',
    cancelled: false,
    attendance_mode: 'in_person',
    venue_name: '',
    address: '',
    online_url: '',
    latitude: '',
    longitude: '',
    category_id: '',
    organiser: '',
    image: '',
    registration: blankRegistration(),
    type: 'event',
    extra: {},
    texts: Object.fromEntries(locales.map((locale, index) => [locale, blankText(index === 0)])),
  };
}

export function toForm(event: EventDetail, locales: readonly string[]): FormState {
  return {
    all_day: event.all_day,
    timezone: event.timezone,
    start: event.start_local,
    end: event.end_local,
    rrule: event.rrule ?? '',
    cancelled: event.cancelled,
    attendance_mode: event.attendance_mode,
    venue_name: event.venue_name ?? '',
    address: event.address ?? '',
    online_url: event.online_url ?? '',
    latitude: event.latitude === null ? '' : String(event.latitude),
    longitude: event.longitude === null ? '' : String(event.longitude),
    category_id: event.category_id ?? '',
    organiser: event.organiser ?? '',
    image: event.image ?? '',
    registration: fromRegistration(event),
    type: event.type,
    extra: event.extra ?? {},
    texts: Object.fromEntries(
      locales.map((locale) => {
        const text = event.texts[locale];
        return [
          locale,
          text
            ? {
                present: true,
                title: text.title,
                slug: text.slug,
                summary: text.summary ?? '',
                description: text.description,
                seo_title: text.seo_title ?? '',
                seo_description: text.seo_description ?? '',
                noindex: text.noindex,
              }
            : blankText(),
        ];
      }),
    ),
  };
}

/** The clock times of a timed event, kept while it is switched to all-day. */
export type TimedClock = { start: string; end: string };

/** Switch between timed and all-day, keeping the dates: an all-day end is the
 *  inclusive last day, a timed end is a clock time on the start's day. Going back
 *  to timed restores the clock times `remembered` from before it was switched to
 *  all-day; an event that never had any gets 09:00 to 10:00. */
export function withAllDay(form: FormState, allDay: boolean, remembered?: TimedClock): FormState {
  if (allDay === form.all_day) return form;
  const [startDay = today(form.timezone)] = form.start.split('T');
  const [endDay = startDay] = form.end.split('T');
  return allDay
    ? { ...form, all_day: true, start: startDay, end: [startDay, endDay].sort()[1] ?? startDay }
    : {
        ...form,
        all_day: false,
        start: `${startDay}T${remembered?.start ?? '09:00'}`,
        end: `${endDay}T${remembered?.end ?? '10:00'}`,
      };
}

/** The clock times of a timed form (`HH:MM`), or `undefined` for an all-day one. */
export function clockOf(form: FormState): TimedClock | undefined {
  if (form.all_day) return undefined;
  const clock = (wall: string) => /T(\d{2}:\d{2})/.exec(wall)?.[1];
  const [start, end] = [clock(form.start), clock(form.end)];
  return start && end ? { start, end } : undefined;
}

const text = (value: string): string | null => (value.trim() === '' ? null : value);
const number = (value: string): number | null => (value.trim() === '' ? null : Number(value));

export const times = (form: FormState): TimesInput => ({
  all_day: form.all_day,
  timezone: form.timezone.trim(),
  start: form.start,
  end: form.end,
});

function fields(form: FormState): EventFields {
  return {
    rrule: text(form.rrule),
    cancelled: form.cancelled,
    attendance_mode: form.attendance_mode,
    venue_name: text(form.venue_name),
    address: text(form.address),
    online_url: text(form.online_url),
    latitude: number(form.latitude),
    longitude: number(form.longitude),
    category_id: text(form.category_id),
    organiser: text(form.organiser),
    image: text(form.image),
  };
}

function textInput(form: TextForm): TextInput {
  return {
    title: form.title.trim(),
    slug: text(form.slug),
    summary: text(form.summary),
    description: form.description,
    seo_title: text(form.seo_title),
    seo_description: text(form.seo_description),
    noindex: form.noindex,
  };
}

export function toCreate(form: FormState, calendarId: string): EventCreate {
  const texts: Record<string, TextInput> = {};
  for (const [locale, entry] of Object.entries(form.texts)) {
    if (entry.present) texts[locale] = textInput(entry);
  }
  const registration = toRegistration(form.registration);
  return {
    calendar_id: calendarId,
    type: form.type,
    extra: form.extra,
    times: times(form),
    texts,
    ...fields(form),
    ...(registration ? { registration } : {}),
  };
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Only what differs from `base`; `null` when nothing does. A language that is
 *  no longer present goes as `null`, which deletes its text. */
export function toPatch(base: FormState, form: FormState, revision: number): EventPatch | null {
  const patch: EventPatch = { expected_revision: revision };
  let changed = false;
  if (!same(times(base), times(form))) {
    patch.times = times(form);
    changed = true;
  }
  const before = fields(base);
  const after = fields(form);
  for (const name of Object.keys(after) as (keyof EventFields)[]) {
    if (same(before[name], after[name])) continue;
    Object.assign(patch, { [name]: after[name] });
    changed = true;
  }
  // Registration goes whole, and only when it changed. Switching it off sends `none`.
  if (!form.registration.hidden && !same(base.registration, form.registration)) {
    patch.registration = toRegistration(form.registration) ?? { mode: 'none' };
    changed = true;
  }
  // `extra` goes only when it changed: an event whose type is not installed has no section, so
  // its form value never differs from the base and its stored bytes are never sent back.
  if (!same(base.extra, form.extra)) {
    patch.extra = form.extra;
    changed = true;
  }
  const texts: Record<string, TextInput | null> = {};
  for (const [locale, entry] of Object.entries(form.texts)) {
    const old = base.texts[locale];
    if (!entry.present) {
      if (old?.present) texts[locale] = null;
    } else if (!old?.present || !same(textInput(old), textInput(entry))) {
      texts[locale] = textInput(entry);
    }
  }
  if (Object.keys(texts).length > 0) {
    patch.texts = texts;
    changed = true;
  }
  return changed ? patch : null;
}

/** A change to when the series happens: it may orphan the overrides written for it. */
export const changesSchedule = (base: FormState, form: FormState): boolean =>
  base.rrule !== form.rrule || !same(times(base), times(form));
