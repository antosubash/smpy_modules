/** A 422 from request validation lists one entry per bad field (`loc`).
 *  Each becomes a localized message next to that field; a field with no
 *  message of its own falls back to the generic one. The module's own refusals
 *  (`invalid_local_time`, `slug_taken`, …) carry a code and no `loc`:
 *  `codeFieldPath` says which input they belong to. */
import { ApiError, CODE } from './api';
import { keys, translate as t } from './i18n';
import { REGISTRATION_CAPACITY_MAX } from './limits';

const E = keys.events.errors;
const MESSAGES: Record<string, string> = {
  name: E.name_invalid,
  names: E.names_invalid,
  slug: E.slug_invalid,
  color: E.color_invalid,
  description: E.description_invalid,
  default_timezone: E.default_timezone_invalid,
  rrule: E.rrule_invalid,
  online_url: E.url_invalid,
  image: E.url_invalid,
  latitude: E.coordinate_invalid,
  longitude: E.coordinate_invalid,
  venue_name: E.text_invalid,
  organiser: E.text_invalid,
  address: E.text_invalid,
  note: E.note_invalid,
  times: E.times_invalid,
  start: E.times_invalid,
  end: E.times_invalid,
  publish_at_local: E.times_invalid,
};
/** `texts.<locale>.<leaf>`: the leaf names the message. */
const TEXT_MESSAGES: Record<string, string> = {
  title: E.title_invalid,
  slug: E.slug_invalid,
  summary: E.summary_invalid,
  description: E.description_too_long,
  seo_title: E.seo_invalid,
  seo_description: E.seo_invalid,
};

/** `registration.<leaf>`: the leaf names the message. */
const REGISTRATION_MESSAGES: Record<string, string> = {
  url: E.url_invalid,
  capacity: E.registration_capacity_invalid,
  opens_at_local: E.registration_window_invalid,
  closes_at_local: E.registration_closes_invalid,
};

/** The values a message names (the capacity maximum comes from the one constant). */
const PARAMS: Record<string, Record<string, unknown>> = {
  [E.registration_capacity_invalid]: {
    max: new Intl.NumberFormat().format(REGISTRATION_CAPACITY_MAX),
  },
};

const messageFor = (path: string): string => {
  const [head = '', ...rest] = path.split('.');
  if (head === 'registration')
    return REGISTRATION_MESSAGES[rest.at(-1) ?? ''] ?? E.invalid_registration;
  if (head === 'texts') return TEXT_MESSAGES[rest.at(-1) ?? ''] ?? E.invalid_input;
  return MESSAGES[head] ?? E.invalid_input;
};

/** `{ field: message }` for a 422, keyed by the full `loc` path (`names.de`,
 *  `texts.de.title`); `{}` for anything else. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.status !== 422) return {};
  const out: Record<string, string> = {};
  for (const path of error.fields) {
    if (!path) continue;
    // A plugin's own words (its model's message) for a path under `extra`; ours for the rest.
    out[path] =
      path.startsWith('extra.') && error.messages[path]
        ? error.messages[path]
        : t(messageFor(path), PARAMS[messageFor(path)]);
  }
  return out;
}

export const requiredText = (): string => t(E.required);

/** The message under a form field; the input points at it with `aria-describedby`. */
export const fieldErrorId = (id: string): string => `${id}-error`;

/** The `aria-*` pair an input with a message needs. */
export const invalidProps = (id: string, message?: string) =>
  message ? { 'aria-invalid': true as const, 'aria-describedby': fieldErrorId(id) } : {};

/** What the event form knows that the server's refusal does not say. */
export type FormContext = {
  defaultLocale: string;
  /** The languages whose slug the user typed, newest first. */
  slugLocales: readonly string[];
};

const AT: Record<string, string> = {
  invalid_local_time: 'times.start',
  end_before_start: 'times.end',
  duration_too_long: 'times.end',
  invalid_rrule: 'rrule',
  rrule_frequency_refused: 'rrule',
  start_not_in_rule: 'times.start',
  unknown_category: 'category_id',
};

/** The input a coded refusal belongs to (`undefined`: none, say it in general). */
export function codeFieldPath(error: unknown, ctx: FormContext): string | undefined {
  if (!(error instanceof ApiError)) return undefined;
  // The server names the input when it knows (which end, which language).
  if (error.field) return error.field;
  // Otherwise a slug conflict is placed only when one language's slug was changed.
  if (error.code === CODE.slugTaken) {
    return ctx.slugLocales.length === 1 ? `texts.${ctx.slugLocales[0]}.slug` : undefined;
  }
  if (error.code === CODE.defaultLocaleRequired) return `texts.${ctx.defaultLocale}.title`;
  return AT[error.code];
}
