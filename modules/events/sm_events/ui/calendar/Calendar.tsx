/** The calendar component: state, fetching, toolbar, filters, status, the lazily loaded
 *  grid, the detail popover and the render slots. It never sees a FullCalendar type; the
 *  grid behind `adapter/` is the one thing a replacement would rewrite. */

import { Button } from '@simple-module-py/ui/components/ui/button';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { RemindMe } from '../reminders/RemindMe';
import { keys, useT } from '../utils/i18n';
import { DetailPopover, type Selected } from './DetailPopover';
import { useOccurrences } from './data/useOccurrences';
import { EventChip } from './EventChip';
import { Filters } from './Filters';
import { lockReason } from './lock';
import { StatusBar } from './StatusBar';
import { Toolbar } from './Toolbar';
import type { Range } from './time/range';
import { browserTimeZone, gridTimeZone, todayIn } from './time/zones';
import {
  type CalendarProps,
  type CalendarState,
  type GridHandle,
  NO_SOURCES,
  type Occurrence,
} from './types';

// The grid, FullCalendar and its CSS are one chunk of their own.
const Grid = lazy(() => import('./adapter/FullCalendarGrid'));

function initialState(props: CalendarProps): CalendarState {
  const all = props.calendars.map((c) => c.id);
  const seed: CalendarState = {
    view: 'month',
    date: '',
    tzMode: 'calendar',
    calendars: all,
    categories: [],
    types: [],
    sources: [],
    ...props.initialState,
  };
  const shown = props.calendars.filter((c) => seed.calendars.includes(c.id));
  const zone = gridTimeZone(seed.tzMode, shown, props.defaultTimezone, browserTimeZone());
  return { ...seed, date: seed.date || todayIn(zone) };
}

export function Calendar(props: CalendarProps) {
  const {
    fetchOccurrences,
    calendars,
    categories = [],
    types = [],
    sources = [],
    editing,
    slots,
  } = props;
  const { t, locale } = useT();
  const copy = keys.events.calendar;
  const [state, setState] = useState(() => initialState(props));
  const [range, setRange] = useState<{ visible: Range; title: string } | null>(null);
  const [selected, setSelected] = useState<Selected | null>(null);
  const grid = useRef<GridHandle>(null);

  const shown = useMemo(
    () => calendars.filter((c) => state.calendars.includes(c.id)),
    [calendars, state.calendars],
  );
  const focusRef = editing?.focusRef;
  useEffect(() => {
    if (focusRef) focusRef.current = (key) => grid.current?.focusEvent(key) ?? false;
  }, [focusRef]);
  const myZone = browserTimeZone();
  const zone = gridTimeZone(state.tzMode, shown, props.defaultTimezone, myZone);
  const calendarZone = gridTimeZone('calendar', shown, props.defaultTimezone, myZone);
  // Nothing is shown when no calendar is checked, or the last source box was unchecked.
  const nothingShown = shown.length === 0 || state.sources.includes(NO_SOURCES);
  const filters = useMemo(
    () => ({
      calendars: shown.length === calendars.length ? [] : state.calendars,
      categories: state.categories,
      types: state.types,
      sources: state.sources,
      locale: locale ?? '',
    }),
    [
      shown.length,
      calendars.length,
      state.calendars,
      state.categories,
      state.types,
      state.sources,
      locale,
    ],
  );
  const data = useOccurrences({
    fetcher: fetchOccurrences,
    visible: nothingShown ? null : (range?.visible ?? null),
    filters,
    refreshToken: props.refreshToken ?? 0,
  });
  const items = nothingShown ? [] : data.items;

  const first = useRef(true);
  const report = useRef(props.onStateChange);
  report.current = props.onStateChange;
  useEffect(() => {
    if (first.current) first.current = false;
    else report.current?.(state);
  }, [state]);

  const patch = useCallback(
    (next: Partial<CalendarState>) => setState((now) => ({ ...now, ...next })),
    [],
  );
  const calendarOf = (o: Occurrence) => calendars.find((c) => c.id === o.calendar_id);
  const reasonOf = (o: Occurrence) => lockReason(o, calendarOf(o), editing, t);
  const close = useCallback(() => setSelected(null), []);

  const renderChip = (o: Occurrence, timeText: string) => {
    const Slot = slots?.EventChip;
    const chip = {
      occurrence: o,
      view: state.view,
      timeText,
      pending: editing?.pendingKeys.has(o.key),
      lockReason: reasonOf(o),
      Default: EventChip,
    };
    return Slot ? <Slot {...chip} /> : <EventChip {...chip} />;
  };

  const selectedOccurrence = selected?.occurrence;
  const actions = selectedOccurrence ? (
    <>
      {selectedOccurrence.url ? (
        <Button asChild size="sm" variant="outline">
          <a href={selectedOccurrence.url}>{t(copy.detail.open_editor)}</a>
        </Button>
      ) : null}
      {editing && selectedOccurrence.editable ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => {
            close();
            editing.onMove(selectedOccurrence, selected?.element);
          }}
        >
          {t(copy.detail.move)}
        </Button>
      ) : null}
      {editing &&
      selectedOccurrence.source === 'events' &&
      selectedOccurrence.event_id &&
      selectedOccurrence.event_status === 'published' ? (
        <RemindMe
          key={selectedOccurrence.event_id}
          eventId={selectedOccurrence.event_id}
          eventZone={selectedOccurrence.timezone}
        />
      ) : null}
    </>
  ) : null;

  const toolbarProps = { state, range: range ? range.visible : null };
  const Start = slots?.ToolbarStart;
  const End = slots?.ToolbarEnd;
  return (
    <div className="space-y-3">
      <Toolbar
        title={range?.title ?? ''}
        view={state.view}
        onView={(view) => patch({ view })}
        onToday={() => grid.current?.today()}
        onPrev={() => grid.current?.prev()}
        onNext={() => grid.current?.next()}
        tz={{
          mode: state.tzMode,
          calendarZone,
          myZone,
          calendarTime: props.calendarTime ?? true,
          onMode: (tzMode) => patch({ tzMode }),
        }}
        start={Start ? <Start {...toolbarProps} /> : null}
        end={End ? <End {...toolbarProps} /> : null}
      />
      <div className="flex flex-col gap-4 lg:flex-row">
        <aside className="lg:w-60 lg:shrink-0">
          <Filters
            state={state}
            calendars={calendars}
            categories={categories}
            types={types}
            sources={sources}
            onChange={patch}
          />
        </aside>
        <div className="min-w-0 flex-1 space-y-2" aria-busy={data.loading}>
          <StatusBar
            loading={data.loading}
            error={data.error}
            empty={items.length === 0}
            truncated={!nothingShown && data.truncated}
            shown={data.items.length}
            sources={nothingShown ? [] : data.sources}
            sourceLabels={sources}
            noCalendars={nothingShown}
            noneExist={calendars.length === 0}
            action={props.noCalendarsAction}
            onRetry={data.retry}
          />
          <Suspense fallback={<Skeleton className="h-[72vh] w-full" />}>
            <Grid
              ref={grid}
              view={state.view}
              date={state.date}
              timeZone={zone}
              locale={locale}
              items={items}
              editing={editing}
              renderChip={renderChip}
              ariaLabel={range?.title || t(copy.region)}
              noEventsText={t(copy.status.empty)}
              onRangeChange={(change) => {
                setRange((now) =>
                  now &&
                  now.title === change.title &&
                  now.visible.start === change.visible.start &&
                  now.visible.end === change.visible.end
                    ? now
                    : { visible: change.visible, title: change.title },
                );
                setState((now) =>
                  now.view === change.view && now.date === change.date
                    ? now
                    : { ...now, view: change.view, date: change.date },
                );
              }}
              onEventOpen={(occurrence, element) => setSelected({ occurrence, element })}
            />
          </Suspense>
        </div>
      </div>
      <DetailPopover
        selected={selected}
        calendar={selectedOccurrence ? calendarOf(selectedOccurrence) : undefined}
        gridTimeZone={zone}
        actions={actions}
        lockReason={selectedOccurrence ? reasonOf(selectedOccurrence) : null}
        Detail={slots?.Detail}
        onClose={close}
        restoreFocus={({ occurrence, element }) =>
          element.isConnected ? element.focus() : grid.current?.focusEvent(occurrence.key)
        }
      />
    </div>
  );
}
