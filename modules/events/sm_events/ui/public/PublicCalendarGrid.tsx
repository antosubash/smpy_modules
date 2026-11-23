import { useCallback, useMemo } from 'react';
import { Calendar } from '../calendar/Calendar';
import type {
  CalendarInfo,
  CalendarState,
  DetailProps,
  FilterOption,
  OccurrenceQuery,
} from '../calendar/types';
import { useEventExtensions } from '../extensions/load';
import { buildSlots } from '../extensions/slots';
import { keys, useT } from '../utils/i18n';
import { publicFetcher } from './api-public';
import { publicGridZone } from './gridZone';
import type { PublicCalendar, PublicCategory } from './types';

/** A detail popover whose one action opens the event's public page. The default's
 *  "open in editor" link is an admin action and has no place here. */
function PublicDetail(props: DetailProps) {
  const { t } = useT();
  const { Default, occurrence } = props;
  const link = occurrence.url ? (
    <a href={occurrence.url} className="underline">
      {t(keys.events.public.item.view_event)}
    </a>
  ) : null;
  return <Default {...props} actions={link} />;
}

type Props = {
  apiUrl: string;
  calendars: PublicCalendar[];
  categories: PublicCategory[];
  defaultTimezone: string;
  initial: Partial<CalendarState>;
  /** Restrict every read to these calendar ids. The grid sends no calendar filter while all the
   *  calendars it was given are shown, which would be every public calendar: a block that names
   *  some calendars asks for exactly those. */
  limitTo?: readonly string[];
  /** Written to the address as the grid moves, so a copied link opens the same month. */
  onState?: (state: CalendarState) => void;
};

/** The read-only grid: PR 3's `Calendar` with no `editing` prop, reading only the public
 *  occurrences endpoint. */
export function PublicCalendarGrid({
  apiUrl,
  calendars,
  categories,
  defaultTimezone,
  initial,
  limitTo,
  onState,
}: Props) {
  const fetcher = useMemo(() => {
    const read = publicFetcher(apiUrl);
    if (!limitTo?.length) return read;
    return (q: OccurrenceQuery, signal: AbortSignal) =>
      read({ ...q, calendars: q.calendars.length > 0 ? q.calendars : [...limitTo] }, signal);
  }, [apiUrl, limitTo]);
  const infos = useMemo<CalendarInfo[]>(
    () =>
      calendars.map((c) => ({
        id: c.id,
        name: c.name,
        color: c.color,
        visibility: 'public',
        default_timezone: c.default_timezone,
        can_write_events: false,
      })),
    [calendars],
  );
  const zone = useMemo(() => publicGridZone(infos, defaultTimezone), [infos, defaultTimezone]);
  const filters = useMemo<FilterOption[]>(
    () => categories.map((c) => ({ id: c.id, label: c.name, color: c.color })),
    [categories],
  );
  const ready = useEventExtensions();
  // biome-ignore lint/correctness/useExhaustiveDependencies: `ready` is the registry's version
  const slots = useMemo(() => buildSlots('public', PublicDetail), [ready]);
  const report = useCallback((state: CalendarState) => onState?.(state), [onState]);
  return (
    <Calendar
      fetchOccurrences={fetcher}
      calendars={infos}
      categories={filters}
      defaultTimezone={zone.defaultTimezone}
      calendarTime={zone.calendarTime}
      initialState={{ tzMode: zone.tzMode, ...initial }}
      onStateChange={report}
      slots={slots}
    />
  );
}
