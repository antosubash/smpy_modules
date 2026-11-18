/** The editor's form state, and its conversion to and from the API's bodies.
 *  Times stay on the event's own wall clock (`YYYY-MM-DDTHH:MM`, or a date all
 *  day): the browser never converts to UTC or to another zone. */
import type {
  AttendanceMode,
  EventCreate,
  EventDetail,
  EventFields,
  EventPatch,
  TextInput,
  TimesInput,
} from './types-events';

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
  registration_url: string;
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

const pad = (n: number) => String(n).padStart(2, '0');
const today = (): string => {
  const now = new Date();
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
};

export function emptyForm(timezone: string, locales: readonly string[]): FormState {
  const day = today();
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
    registration_url: '',
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
    registration_url: event.registration_url ?? '',
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

/** Switch between timed and all-day, keeping the dates: an all-day end is the
 *  inclusive last day, a timed end is a clock time on the start's day. */
export function withAllDay(form: FormState, allDay: boolean): FormState {
  if (allDay === form.all_day) return form;
  const [startDay = today()] = form.start.split('T');
  const [endDay = startDay] = form.end.split('T');
  return allDay
    ? { ...form, all_day: true, start: startDay, end: [startDay, endDay].sort()[1] ?? startDay }
    : { ...form, all_day: false, start: `${startDay}T09:00`, end: `${endDay}T10:00` };
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
    registration_url: text(form.registration_url),
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
  return { calendar_id: calendarId, times: times(form), texts, ...fields(form) };
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
