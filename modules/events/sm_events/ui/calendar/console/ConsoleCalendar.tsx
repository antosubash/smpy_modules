/** The console's `Calendar`: the occurrence fetcher over the events API, the content language
 *  titles are asked in, the filter options and the write layer (drag, resize, dialogs). */
import { Link } from '@inertiajs/react';
import { useCallback, useMemo, useRef, useState } from 'react';
import { extensionFailures, useEventExtensions } from '../../extensions/load';
import { buildSlots } from '../../extensions/slots';
import { translateKey } from '../../extensions/translateKey';
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
import { useFocusReturn } from './focusReturn';
import { MoveDialog } from './MoveDialog';
import { QuickCreateDialog } from './QuickCreateDialog';
import { useCalendarWrites } from './useCalendarWrites';

export type TypeOption = { id: string; label_key: string; icon?: string | null };
export type SourceOption = { id: string; label_key: string; color: string | null };

type Props = {
  calendars: CalendarInfo[];
  categories: Category[];
  defaultTimezone: string;
  contentLocales: string[];
  editorUrl: string;
  /** The Calendars screen, for someone who may create one; absent otherwise. */
  calendarsUrl?: string;
  /** The installed event types (the server's), for the type filter. */
  types?: TypeOption[];
  /** The installed plugin sources enabled on a shown calendar. */
  sources?: SourceOption[];
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
  calendarsUrl,
  types: typeOptions,
  sources: sourceOptions,
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
          source: q.sources,
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
  const types = useMemo(
    () =>
      typeOptions?.length
        ? typeOptions.map((o) => ({ id: o.id, label: translateKey(t, o.label_key, o.id) }))
        : [{ id: 'event', label: t(keys.events.calendar.type_event) }],
    [t, typeOptions],
  );
  const sources = useMemo(
    () =>
      (sourceOptions ?? []).map((o) => ({
        id: o.id,
        color: o.color,
        label: translateKey(t, o.label_key, o.id),
      })),
    [t, sourceOptions],
  );
  const ready = useEventExtensions();
  // Rebuilt when the plugins have registered; until then the defaults render.
  // biome-ignore lint/correctness/useExhaustiveDependencies: `ready` is the registry's version
  const slots = useMemo(() => buildSlots('console'), [ready]);
  // A write refetches the range it changed.
  const [refresh, setRefresh] = useState(0);
  const invalidate = useCallback(() => setRefresh((n) => n + 1), []);
  const focusRef = useRef<((key: string) => boolean) | null>(null);
  const focusEvent = useCallback((key: string) => void focusRef.current?.(key), []);
  const writes = useCalendarWrites({ invalidate, editorUrl, focusEvent });
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
      // Nothing opens without a shown calendar the user can write to.
      onCreate: (next) => canCreate && setSlot(next),
      onChange: writes.onChange,
      onMove: (occurrence, element) => setMoving({ occurrence, element: element ?? null }),
      pendingKeys: writes.pendingKeys,
      focusRef,
    }),
    [canCreate, slot, writes.onChange, writes.pendingKeys],
  );
  const restoreFocus = useFocusReturn(focusRef);
  return (
    <>
      <Calendar
        fetchOccurrences={fetchOccurrences}
        calendars={calendars}
        categories={options}
        types={types}
        sources={sources}
        slots={slots}
        defaultTimezone={defaultTimezone}
        initialState={initialState}
        onStateChange={(state) => {
          setShown(state.calendars);
          onStateChange?.(state);
        }}
        editing={editing}
        refreshToken={refresh}
        noCalendarsAction={
          calendarsUrl ? (
            <Link className="underline" href={calendarsUrl}>
              {t(keys.events.calendar.status.open_calendars)}
            </Link>
          ) : null
        }
      />
      {ready && extensionFailures().length > 0 ? (
        <p
          role="status"
          className="mt-2 text-xs text-muted-foreground"
          data-testid="extension-failed"
        >
          {t(keys.events.extensions.load_failed)}
        </p>
      ) : null}
      {writes.dialogs}
      <MoveDialog
        occurrence={moving?.occurrence ?? null}
        returnFocus={moving?.element}
        restoreFocus={restoreFocus}
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
