/** The only FullCalendar mount. Everything it decides lives in `mapping.ts` and `options.ts`
 *  (unit-tested); this file only wires the library to the shell's `GridProps`/`GridHandle`.
 *  It is loaded lazily, so the library and its CSS stay out of every other chunk. */
import FullCalendar, { type CalendarRef } from '@fullcalendar/react';
import '@fullcalendar/react/skeleton.css';
import '@fullcalendar/react/themes/classic/theme.css';
import { type Ref, useEffect, useImperativeHandle, useMemo, useRef } from 'react';
import type { GridHandle, GridProps } from '../types';
import './calendar.css';
import {
  acceptsSelection,
  allowDrop,
  chipFor,
  type DragInfo,
  type EditedEvent,
  occurrenceOf,
  type Placement,
  skipsWallTime,
  toChange,
  toEventInput,
  toRangeChange,
  toSlot,
  VIEW_NAMES,
} from './mapping';
import { baseOptions, localeOptions, PLUGINS } from './options';

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
  const section = useRef<HTMLElement>(null);

  useImperativeHandle(ref, () => ({
    today: () => calendar.current?.getApi().today(),
    prev: () => calendar.current?.getApi().prev(),
    next: () => calendar.current?.getApi().next(),
    setView: (next) => calendar.current?.getApi().changeView(VIEW_NAMES[next]),
    gotoDate: (next) => calendar.current?.getApi().gotoDate(next),
    focusEvent: (key) => {
      const element = elements.current.get(key);
      if (!element?.isConnected) return false;
      element.focus();
      return true;
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

  // Where drops are shown while their writes run. A fresh page of items already carries the
  // server's answer, so the entries end with it.
  const placed = useRef(new Map<string, Placement>());
  // biome-ignore lint/correctness/useExhaustiveDependencies: `items` is the trigger, not a read
  useEffect(() => placed.current.clear(), [items]);
  // The selection stays while the create dialog is open and goes with it.
  const creating = Boolean(editing?.creating);
  useEffect(() => {
    if (!creating) calendar.current?.getApi().unselect();
  }, [creating]);
  const events = useMemo(
    () => items.map((o) => toEventInput(o, editing, placed.current.get(o.key))),
    [items, editing],
  );

  /** A drop or resize: show it at once, ask the shell, and put it back on any refusal. */
  async function apply(
    kind: 'move' | 'resize',
    info: DragInfo & {
      event: EditedEvent & { extendedProps: Record<string, unknown> };
      revert: () => void;
    },
  ) {
    const occurrence = occurrenceOf(info.event);
    if (!editing) return info.revert();
    const change = toChange(kind, occurrence, info.event);
    if (skipsWallTime(kind, info.oldEvent, info, timeZone)) change.skipsWallTime = true;
    placed.current.set(occurrence.key, { start: change.start, end: change.end });
    let keep = false;
    try {
      keep = await editing.onChange(change);
    } finally {
      if (!keep) {
        placed.current.delete(occurrence.key);
        info.revert();
      }
    }
  }

  return (
    <section ref={section} className="sm-ev-calendar" aria-label={ariaLabel}>
      <FullCalendar
        ref={calendar}
        plugins={PLUGINS}
        {...baseOptions()}
        {...localeOptions(locale)}
        initialView={VIEW_NAMES[view]}
        initialDate={date}
        timeZone={timeZone}
        events={events}
        editable={Boolean(editing)}
        selectable={Boolean(editing?.canCreate)}
        selectMirror
        // A click selects one slot, so `select` covers it; `dateClick` is the same slot again.
        select={(info) => {
          if (acceptsSelection(editing)) editing?.onCreate(toSlot(info));
          else calendar.current?.getApi().unselect();
        }}
        dateClick={(info) =>
          acceptsSelection(editing) &&
          editing?.onCreate(
            toSlot({
              start: info.date,
              end: null,
              allDay: info.allDay,
              startStr: info.dateStr,
              endStr: '',
            }),
          )
        }
        noEventsContent={noEventsText}
        // A React node, never `{html}`: a title is text.
        eventContent={({ event, timeText }) =>
          chipFor(event, timeText, renderChip, timeZone, locale)
        }
        eventDidMount={({ event, el }) => {
          elements.current.set(event.id, el);
        }}
        eventWillUnmount={({ event, el }) => {
          if (elements.current.get(event.id) === el) elements.current.delete(event.id);
        }}
        eventClick={({ event, el }) =>
          onEventOpen(occurrenceOf(event), elements.current.get(event.id) ?? el)
        }
        eventDrop={(info) => void apply('move', info)}
        eventResize={(info) => void apply('resize', info)}
        eventAllow={(span, moving) =>
          moving ? allowDrop(occurrenceOf(moving), span.allDay) : true
        }
        datesSet={(info) => {
          const change = toRangeChange(info, timeZone);
          reportedDate.current = change.date;
          // The view FullCalendar has actually drawn (not the one asked for): a stable hook for a
          // test or a script to know the switch is done.
          section.current?.setAttribute('data-view', change.view);
          onRangeChange(change);
        }}
      />
    </section>
  );
}
