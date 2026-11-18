import type { FormState } from './event-form';
import { requiredText } from './field-errors';

/** The form's own checks before any request, keyed by field path. */
export const FIELDS = [
  'times.start',
  'times.end',
  'times.timezone',
  'rrule',
  'category_id',
  'online_url',
  'registration_url',
  'image',
  'latitude',
  'longitude',
  'venue_name',
  'organiser',
  'address',
];
export const TEXT_FIELDS = [
  'title',
  'slug',
  'summary',
  'description',
  'seo_title',
  'seo_description',
];
export const TEXT_PATH = /^texts\.([^.]+)\./;

export function validate(
  form: FormState,
  defaultLocale: string,
  incomplete: boolean,
): Record<string, string> {
  const found: Record<string, string> = {};
  for (const [locale, text] of Object.entries(form.texts)) {
    if ((text.present || locale === defaultLocale) && !text.title.trim()) {
      found[`texts.${locale}.title`] = requiredText();
    }
  }
  if (!form.start) found['times.start'] = requiredText();
  if (!form.end) found['times.end'] = requiredText();
  if (!form.timezone.trim()) found['times.timezone'] = requiredText();
  if (incomplete) found['rrule.until'] = requiredText();
  return found;
}
