/** Static FullCalendar options and the locale choice. */
import type { LocaleInput } from '@fullcalendar/react';
import de from '@fullcalendar/react/locales/de';

/** The German data starts the week on Monday and the day on a 24-hour clock; English uses
 *  the library's built-in data (Sunday, 12-hour). Any other console language also falls back
 *  to the built-in English, as the console's own catalogues do. */
export function localeFor(code: string | undefined): LocaleInput | 'en' {
  return code?.toLowerCase().split('-')[0] === 'de' ? de : 'en';
}

export function localeOptions(code: string | undefined): {
  locale: string;
  locales?: LocaleInput[];
} {
  const data = localeFor(code);
  return data === 'en' ? { locale: 'en' } : { locale: data.code ?? 'de', locales: [data] };
}

export function baseOptions() {
  return {
    headerToolbar: false as const,
    eventInteractive: true,
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
