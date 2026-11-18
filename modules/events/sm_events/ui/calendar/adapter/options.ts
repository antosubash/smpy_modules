/** Static FullCalendar options and the locale choice. */
import type { LocaleInput } from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/react/daygrid';
import interactionPlugin from '@fullcalendar/react/interaction';
import listPlugin from '@fullcalendar/react/list';
import de from '@fullcalendar/react/locales/de';
import classicTheme from '@fullcalendar/react/themes/classic';
import timeGridPlugin from '@fullcalendar/react/timegrid';

/** The interaction plugin is what makes `editable`, `selectable`, `dateClick` and `select` do
 *  anything: without it the grid renders and clicks open events, but nothing can be dragged,
 *  resized or selected. */
export const PLUGINS = [dayGridPlugin, timeGridPlugin, listPlugin, interactionPlugin, classicTheme];

/** The German data starts the week on Monday and the day on a 24-hour clock; English uses
 *  the library's built-in data (Sunday, 12-hour). Any other console language also falls back
 *  to the built-in English, as the console's own catalogues do. */
export function localeFor(code: string | undefined): LocaleInput | 'en' {
  return code?.toLowerCase().split('-')[0] === 'de' ? de : 'en';
}

const LOCALE_OPTIONS = new Map<string, { locale: string; locales?: LocaleInput[] }>();

/** One stable object per language: FullCalendar re-reads `locales` whenever the array's
 *  identity changes, and each re-read fires `datesSet` again, which re-renders the shell,
 *  which builds a new array: an endless loop (React error 185) in German. */
export function localeOptions(code: string | undefined): {
  locale: string;
  locales?: LocaleInput[];
} {
  const data = localeFor(code);
  const key = data === 'en' ? 'en' : (data.code ?? 'de');
  let options = LOCALE_OPTIONS.get(key);
  if (!options) {
    options = data === 'en' ? { locale: 'en' } : { locale: key, locales: [data] };
    LOCALE_OPTIONS.set(key, options);
  }
  return options;
}

export function baseOptions() {
  return {
    headerToolbar: false as const,
    eventInteractive: true,
    // Without the meridiem a 3 pm block reads "3:00", the same as 3 am.
    eventTimeFormat: { hour: 'numeric' as const, minute: '2-digit' as const },
    fixedWeekCount: false,
    nowIndicator: true,
    dayMaxEvents: true,
    slotDuration: '00:30:00',
    scrollTime: '08:00:00',
    height: '72vh',
    editable: false,
    selectable: false,
  };
}
