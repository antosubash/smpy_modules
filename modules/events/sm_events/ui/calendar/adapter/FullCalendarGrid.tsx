/** The only FullCalendar mount. Everything it decides lives in `mapping.ts` and `options.ts`
 *  (unit-tested); this file only wires the library to the shell's `GridProps`/`GridHandle`.
 *  It is loaded lazily, so the library and its CSS stay out of every other chunk. */
import FullCalendar, { type CalendarRef } from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/react/daygrid';
import listPlugin from '@fullcalendar/react/list';
import '@fullcalendar/react/skeleton.css';
import classicTheme from '@fullcalendar/react/themes/classic';
import '@fullcalendar/react/themes/classic/theme.css';
import timeGridPlugin from '@fullcalendar/react/timegrid';
import { type Ref, useEffect, useImperativeHandle, useMemo, useRef } from 'react';
import type { GridHandle, GridProps } from '../types';
import './calendar.css';
import { allowDrop, occurrenceOf, toEventInput, toRangeChange, VIEW_NAMES } from './mapping';
import { baseOptions, localeOptions } from './options';

const PLUGINS = [dayGridPlugin, timeGridPlugin, listPlugin, classicTheme];

export default function FullCalendarGrid({
  ref,
  view,
  date,
  timeZone,
  locale,
  items,
  editing,
  renderChip,
  onRangeChange,
  onEventOpen,
  ariaLabel,
  noEventsText,
}: GridProps & { ref?: Ref<GridHandle> }) {
  const calendar = useRef<CalendarRef>(null);
  const elements = useRef(new Map<string, HTMLElement>());
  const reportedDate = useRef(date);

  useImperativeHandle(ref, () => ({
    today: () => calendar.current?.getApi().today(),
    prev: () => calendar.current?.getApi().prev(),
    next: () => calendar.current?.getApi().next(),
    setView: (next) => calendar.current?.getApi().changeView(VIEW_NAMES[next]),
    gotoDate: (next) => calendar.current?.getApi().gotoDate(next),
    focusEvent: (key) => {
      const element = elements.current.get(key);
      if (element?.isConnected) element.focus();
    },
  }));

  // The shell owns `view` and `date`; the grid follows them (and reports back through
  // `datesSet`, which updates `reportedDate` first so this never loops).
  useEffect(() => {
    const grid = calendar.current?.getApi();
    if (grid && grid.view.type !== VIEW_NAMES[view]) grid.changeView(VIEW_NAMES[view]);
  }, [view]);
  useEffect(() => {
    if (date !== reportedDate.current) calendar.current?.getApi().gotoDate(date);
  }, [date]);

  const events = useMemo(() => items.map((o) => toEventInput(o, editing)), [items, editing]);

  return (
    <section className="sm-ev-calendar" aria-label={ariaLabel}>
      <FullCalendar
        ref={calendar}
        plugins={PLUGINS}
        {...baseOptions()}
        {...localeOptions(locale)}
        initialView={VIEW_NAMES[view]}
        initialDate={date}
        timeZone={timeZone}
        events={events}
        noEventsContent={noEventsText}
        // A React node, never `{html}`: a title is text.
        eventContent={({ event, timeText }) => renderChip(occurrenceOf(event), timeText)}
        eventDidMount={({ event, el }) => {
          elements.current.set(event.id, el);
        }}
        eventWillUnmount={({ event, el }) => {
          if (elements.current.get(event.id) === el) elements.current.delete(event.id);
        }}
        eventClick={({ event, el }) =>
          onEventOpen(occurrenceOf(event), elements.current.get(event.id) ?? el)
        }
        eventAllow={(span, moving) =>
          moving ? allowDrop(occurrenceOf(moving), span.allDay) : true
        }
        datesSet={(info) => {
          const change = toRangeChange(info, timeZone);
          reportedDate.current = change.date;
          onRangeChange(change);
        }}
      />
    </section>
  );
}
