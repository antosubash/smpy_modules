/** The console's `Calendar`: the occurrence fetcher over the events API, the content language
 *  titles are asked in, and the filter options. (Editing joins it in the write layer.) */
import { useCallback, useMemo } from 'react';
import { listOccurrences } from '../../utils/api-events';
import { keys, useT } from '../../utils/i18n';
import type { Category } from '../../utils/types';
import { Calendar } from '../Calendar';
import type { CalendarInfo, CalendarState, FilterOption, OccurrenceFetcher } from '../types';

type Props = {
  calendars: CalendarInfo[];
  categories: Category[];
  defaultTimezone: string;
  contentLocales: string[];
  initialState?: Partial<CalendarState>;
  onStateChange?: (state: CalendarState) => void;
};

/** The language titles are asked in: the console's, when it is a content language. */
export function requestedLocale(current: string | undefined, contentLocales: string[]): string {
  const language = current?.split('-')[0];
  return language && contentLocales.includes(language) ? language : (contentLocales[0] ?? 'en');
}

export function ConsoleCalendar({
  calendars,
  categories,
  defaultTimezone,
  contentLocales,
  initialState,
  onStateChange,
}: Props) {
  const { t, locale } = useT();
  const requested = requestedLocale(locale, contentLocales);
  const fetchOccurrences = useCallback<OccurrenceFetcher>(
    (q, signal) =>
      listOccurrences(
        {
          start: q.start,
          end: q.end,
          calendar: q.calendars,
          category: q.categories,
          type: q.types,
          locale: requested,
        },
        signal,
      ),
    [requested],
  );
  const options = useMemo<FilterOption[]>(
    () =>
      categories.map((category) => ({
        id: category.id,
        color: category.color,
        label: category.names[requested] ?? Object.values(category.names)[0] ?? category.slug,
      })),
    [categories, requested],
  );
  const types = useMemo(() => [{ id: 'event', label: t(keys.events.calendar.type_event) }], [t]);
  return (
    <Calendar
      fetchOccurrences={fetchOccurrences}
      calendars={calendars}
      categories={options}
      types={types}
      defaultTimezone={defaultTimezone}
      initialState={initialState}
      onStateChange={onStateChange}
    />
  );
}
