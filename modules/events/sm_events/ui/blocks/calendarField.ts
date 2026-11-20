/** The `calendars` field both blocks share, and the choices it offers.
 *
 *  A block references calendars by *slug* (resolved by the server on every request, so a renamed
 *  calendar keeps working through its redirects). The choices come from the anonymous route, which
 *  lists exactly what a block can render, so the picker needs no console permission and cannot
 *  offer a calendar the public may not see. */

import { keys, type Translate, translate } from '../utils/i18n';
import { fetchBlockCalendars } from './api-blocks';
import { CALENDARS_MAX } from './limits';

export type Option = { label: string; value: string };

const copy = keys.events.blocks;

/** The array field. Labels are catalogue keys until `localizeFields` resolves them. */
export function calendarsField(tr: Translate, label: string, options: Option[]) {
  return {
    type: 'array' as const,
    label: tr(label),
    max: CALENDARS_MAX,
    arrayFields: {
      slug: {
        type: 'select' as const,
        label: tr(copy.fields.calendar),
        options: [{ label: tr(copy.fields.calendar_all), value: '' }, ...options],
      },
    },
    defaultItemProps: { slug: '' },
    // Called by Puck on every render of the field, long after the labels above were built: it
    // translates then, never at build time (`tr` may be the identity of the static fields).
    getItemSummary: (item: { slug?: string }) => item.slug || translate(copy.fields.calendar),
  };
}

/** Every public calendar as a choice. Empty when the route cannot be reached (the editor offline,
 *  the module without a public surface): that must not break the editor. */
export async function loadCalendarOptions(signal: AbortSignal): Promise<Option[]> {
  try {
    const answer = await fetchBlockCalendars([], '', signal);
    return answer.calendars.map((c) => ({ label: c.name, value: c.slug }));
  } catch {
    return [];
  }
}
