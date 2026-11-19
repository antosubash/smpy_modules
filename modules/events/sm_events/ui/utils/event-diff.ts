/** What differs between the form (yours) and another version of the event
 *  (theirs), for the conflict panel: each differing field, in words. */
import type { FormState, TextForm } from './event-form';
import { keys, translate as t } from './i18n';
import { languageName } from './language';

export type Difference = { id: string; label: string; theirs: string; mine: string };

const E = keys.events.editor;
const FIELDS: [keyof FormState, string][] = [
  ['all_day', E.all_day],
  ['start', E.start],
  ['end', E.end],
  ['timezone', E.timezone],
  ['rrule', keys.events.recurrence.title],
  ['cancelled', E.cancelled],
  ['attendance_mode', E.attendance],
  ['venue_name', E.venue],
  ['address', E.address],
  ['online_url', E.online_url],
  ['latitude', E.latitude],
  ['longitude', E.longitude],
  ['category_id', E.category],
  ['organiser', E.organiser],
  ['image', E.image],
  ['registration_url', E.registration_url],
];
const TEXT_FIELDS: [keyof TextForm, string][] = [
  ['title', keys.events.texts.title],
  ['slug', keys.events.texts.slug],
  ['summary', keys.events.texts.summary],
  ['description', keys.events.texts.description],
  ['seo_title', keys.events.texts.seo_title],
  ['seo_description', keys.events.texts.seo_description],
  ['noindex', keys.events.texts.noindex],
];
const SHORT = 100;

/** Rich text as the plain words it holds, so two descriptions can be compared by eye. */
function plain(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  return (doc.body.textContent ?? '').replace(/\s+/g, ' ').trim();
}

function show(name: string, value: string | boolean, category: (id: string) => string): string {
  if (typeof value === 'boolean')
    return t(value ? keys.events.conflict.yes : keys.events.conflict.no);
  const text =
    name === 'description' ? plain(value) : name === 'category_id' ? category(value) : value;
  if (!text) return t(keys.events.conflict.empty);
  if (name === 'attendance_mode') return t(E[`attendance_${value}` as 'attendance_online']);
  return text.length > SHORT ? `${text.slice(0, SHORT)}…` : text;
}

export function diffForms(
  mine: FormState,
  theirs: FormState,
  { ui, category = (id: string) => id }: { ui?: string; category?: (id: string) => string } = {},
): Difference[] {
  const out: Difference[] = [];
  for (const [name, label] of FIELDS) {
    if (mine[name] === theirs[name]) continue;
    out.push({
      id: name,
      label: t(name === 'end' && mine.all_day ? E.last_day : label),
      theirs: show(name, theirs[name] as string | boolean, category),
      mine: show(name, mine[name] as string | boolean, category),
    });
  }
  for (const locale of Object.keys(mine.texts)) {
    const a = mine.texts[locale];
    const b = theirs.texts[locale];
    if (!a || !b) continue;
    const language = languageName(locale, ui);
    if (a.present !== b.present) {
      out.push({
        id: `texts.${locale}`,
        label: t(keys.events.conflict.language_changed, { language }),
        theirs: t(b.present ? keys.events.conflict.yes : keys.events.conflict.no),
        mine: t(a.present ? keys.events.conflict.yes : keys.events.conflict.no),
      });
      continue;
    }
    if (!a.present) continue;
    for (const [name, label] of TEXT_FIELDS) {
      if (a[name] === b[name]) continue;
      out.push({
        id: `texts.${locale}.${name}`,
        label: `${t(label)} (${language})`,
        theirs: show(name, b[name], category),
        mine: show(name, a[name], category),
      });
    }
  }
  return out;
}
