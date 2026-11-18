/** The console's `Calendar`: the occurrence fetcher over the events API, the content language
 *  titles are asked in, the filter options and the write layer (drag, resize, dialogs). */
import { useCallback, useMemo, useState } from 'react';
import { listOccurrences } from '../../utils/api-events';
import { keys, useT } from '../../utils/i18n';
import type { Category } from '../../utils/types';
import { Calendar } from '../Calendar';
import type {
  CalendarEditing,
  CalendarInfo,
  CalendarState,
  CreateSlot,
  FilterOption,
  Occurrence,
  OccurrenceFetcher,
} from '../types';
import { MoveDialog } from './MoveDialog';
import { QuickCreateDialog } from './QuickCreateDialog';
import { useCalendarWrites } from './useCalendarWrites';

type Props = {
  calendars: CalendarInfo[];
  categories: Category[];
  defaultTimezone: string;
  contentLocales: string[];
  editorUrl: string;
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
  editorUrl,
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
  // A write refetches the range it changed.
  const [refresh, setRefresh] = useState(0);
  const invalidate = useCallback(() => setRefresh((n) => n + 1), []);
  const writes = useCalendarWrites({ invalidate, editorUrl });
  const [slot, setSlot] = useState<CreateSlot | null>(null);
  const [moving, setMoving] = useState<{
    occurrence: Occurrence;
    element: HTMLElement | null;
  } | null>(null);
  // A new event goes to a calendar the filter shows (a draft on a hidden one would never
  // appear), and starts on the shown one when exactly one is.
  const [shown, setShown] = useState(initialState?.calendars ?? calendars.map((c) => c.id));
  const shownCalendars = useMemo(
    () => calendars.filter((c) => shown.includes(c.id)),
    [calendars, shown],
  );
  const preferred = shownCalendars.length === 1 ? (shownCalendars[0]?.id ?? null) : null;
  const canCreate = shownCalendars.some((c) => c.can_write_events);
  const editing = useMemo<CalendarEditing>(
    () => ({
      canCreate,
      creating: slot !== null,
      onCreate: setSlot,
      onChange: writes.onChange,
      onMove: (occurrence, element) => setMoving({ occurrence, element: element ?? null }),
      pendingKeys: writes.pendingKeys,
    }),
    [canCreate, slot, writes.onChange, writes.pendingKeys],
  );
  return (
    <>
      <Calendar
        fetchOccurrences={fetchOccurrences}
        calendars={calendars}
        categories={options}
        types={types}
        defaultTimezone={defaultTimezone}
        initialState={initialState}
        onStateChange={(state) => {
          setShown(state.calendars);
          onStateChange?.(state);
        }}
        editing={editing}
        refreshToken={refresh}
      />
      {writes.dialogs}
      <MoveDialog
        occurrence={moving?.occurrence ?? null}
        returnFocus={moving?.element}
        onSubmit={writes.submit}
        onClose={() => setMoving(null)}
      />
      <QuickCreateDialog
        slot={slot}
        calendars={shownCalendars}
        preferred={preferred}
        defaultLocale={contentLocales[0] ?? 'en'}
        editorUrl={editorUrl}
        onCreated={invalidate}
        onClose={() => setSlot(null)}
      />
    </>
  );
}
