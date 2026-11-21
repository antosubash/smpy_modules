/** Occurrences to FullCalendar events and FullCalendar's callbacks back to ours. Pure, so it
 *  is unit-tested without a browser; only types come from the library. */
import type { EventInput } from '@fullcalendar/react';
import { Temporal } from 'temporal-polyfill';
import { readableOn } from '../../utils/contrast';
import type { Occurrence } from '../../utils/types-events';
import { chipTime, readsBackwards } from '../time/format';
import { DEFAULT_CREATE_MINUTES, SLOT_MINUTES } from '../time/range';
import { addDays, dateIn, isNonexistent } from '../time/zones';
import type {
  CalendarEditing,
  CalendarView,
  CreateSlot,
  OccurrenceChange,
  RangeChange,
} from '../types';

export const VIEW_NAMES: Record<CalendarView, string> = {
  month: 'dayGridMonth',
  week: 'timeGridWeek',
  day: 'timeGridDay',
  list: 'listMonth',
};

export function viewOfName(name: string): CalendarView {
  const found = (Object.keys(VIEW_NAMES) as CalendarView[]).find(
    (view) => VIEW_NAMES[view] === name,
  );
  return found ?? 'month';
}

/** Draft, in review and cancelled are marked with these (and with words in the chip), so no
 *  state rests on colour alone. Pending is a write in flight. */
function statusClasses(o: Occurrence, pending: boolean): string | undefined {
  const names = [
    o.event_status === 'draft' && 'sm-ev-draft',
    o.event_status === 'in_review' && 'sm-ev-review',
    o.status === 'cancelled' && 'sm-ev-cancelled',
    pending && 'sm-ev-pending',
  ].filter(Boolean);
  return names.length ? names.join(' ') : undefined;
}

/** Where the user dropped an occurrence while its write is in flight, in a change's
 *  encoding (instants, or dates with an exclusive end). Rebuilding the events for a pending
 *  mark must not snap the occurrence back to where the server still has it. */
export type Placement = { start: string; end: string };

export function toEventInput(
  o: Occurrence,
  editing: CalendarEditing | undefined,
  placement?: Placement,
): EventInput {
  const pending = Boolean(editing?.pendingKeys.has(o.key));
  const movable = Boolean(editing) && o.editable && o.status !== 'cancelled' && !pending;
  return {
    id: o.key,
    title: o.title,
    allDay: o.all_day,
    // An all-day occurrence is dates, which FullCalendar never shifts by a zone.
    start: placement?.start ?? (o.all_day ? (o.start_date ?? o.start) : o.start),
    end: placement?.end ?? (o.all_day ? (o.end_date ?? o.end) : o.end),
    color: o.color,
    textColor: readableOn(o.color),
    interactive: true,
    startEditable: movable,
    durationEditable: movable,
    className: statusClasses(o, pending),
    // The url stays out of the event: FullCalendar would render a link instead of opening
    // the popover.
    extendedProps: { occurrence: o },
  };
}

export const occurrenceOf = (event: { extendedProps: Record<string, unknown> }): Occurrence =>
  event.extendedProps.occurrence as Occurrence;

/** The chip for a grid event, or `undefined` for one that is not an occurrence: the
 *  selection mirror and the drag helper FullCalendar draws carry no `extendedProps`, and
 *  those keep the library's own rendering. */
export function chipFor<T>(
  event: { extendedProps: Record<string, unknown> },
  timeText: string,
  render: (occurrence: Occurrence, timeText: string) => T,
  timeZone?: string,
  locale?: string,
): T | undefined {
  const occurrence = event.extendedProps.occurrence as Occurrence | undefined;
  if (!occurrence) return undefined;
  // The library's own range text cannot tell the two passes of a repeated hour apart.
  const text =
    timeZone && !occurrence.all_day && readsBackwards(occurrence, timeZone)
      ? timeText && chipTime(occurrence, timeZone, locale)
      : timeText;
  return render(occurrence, text);
}

/** What an edited `EventApi` reports (the library's own type satisfies it). */
export type EditedEvent = {
  start: Date | null;
  end: Date | null;
  allDay: boolean;
  startStr: string;
  endStr: string;
};

const instant = (date: Date): string =>
  Temporal.Instant.fromEpochMilliseconds(date.getTime()).toString();
const day = (text: string): string => text.slice(0, 10);

/** What FullCalendar reports after a drop or resize. Timed edges are true instants; all-day
 *  edges are dates, the end exclusive (an event with no end is one day). */
export function toChange(
  kind: 'move' | 'resize',
  occurrence: Occurrence,
  edited: EditedEvent,
): OccurrenceChange {
  if (edited.allDay) {
    const start = day(edited.startStr);
    const end = edited.endStr ? day(edited.endStr) : addDays(start, 1);
    return { occurrence, kind, start, end, allDay: true };
  }
  const start = edited.start ? instant(edited.start) : occurrence.start;
  const end = edited.end
    ? instant(edited.end)
    : Temporal.Instant.from(start)
        .add({
          milliseconds:
            Temporal.Instant.from(occurrence.end).epochMilliseconds -
            Temporal.Instant.from(occurrence.start).epochMilliseconds,
        })
        .toString();
  return { occurrence, kind, start, end, allDay: false };
}

/** FullCalendar's civil delta: calendar units plus milliseconds, applied to a wall time. */
export type CivilDelta = { years: number; months: number; days: number; milliseconds: number };
export type DragInfo = {
  oldEvent: EditedEvent;
  delta?: CivilDelta;
  startDelta?: CivilDelta;
  endDelta?: CivilDelta;
};

function wallAfter(edgeStr: string, delta: CivilDelta): string {
  const { years, months, days, milliseconds } = delta;
  // Two steps: a Temporal duration cannot mix the signs of its fields.
  return Temporal.PlainDateTime.from(edgeStr.slice(0, 19))
    .add({ years, months, days })
    .add({ milliseconds })
    .toString();
}

/** Whether the wall time the pointer meant is one the grid's zone skips. FullCalendar hands
 *  back an instant it has already moved forward out of the gap, so the intent is rebuilt
 *  from what it does keep: the old edge's wall time and the civil delta (the time grid is
 *  wall-clock based). A move is judged by its start, a resize by the edge it pulled. */
export function skipsWallTime(
  kind: 'move' | 'resize',
  old: EditedEvent,
  info: Omit<DragInfo, 'oldEvent'>,
  timeZone: string,
): boolean {
  if (old.allDay) return false;
  const edges: [string, CivilDelta | undefined][] =
    kind === 'move'
      ? [[old.startStr, info.delta]]
      : [
          [old.startStr, info.startDelta],
          [old.endStr, info.endDelta],
        ];
  return edges.some(
    ([edge, delta]) =>
      Boolean(edge && delta) && isNonexistent(wallAfter(edge, delta as CivilDelta), timeZone),
  );
}

/** Whether a click or a selection on the grid may start a new event: something writable is
 *  shown, and no write is in flight (a press on a busy chip must not become a selection). */
export const acceptsSelection = (editing: CalendarEditing | undefined): boolean =>
  Boolean(editing?.canCreate) && editing?.pendingKeys.size === 0;

/** A drag between the all-day row and the time grid would change `all_day`: refused (the
 *  Move dialog and the editor do that). */
export const allowDrop = (o: Occurrence, dropAllDay: boolean): boolean => o.all_day === dropAllDay;

type DatesSet = {
  start: Date;
  end: Date;
  view: { type: string; title: string; currentStart: Date };
};

export function toRangeChange(info: DatesSet, timeZone: string): RangeChange {
  return {
    visible: { start: instant(info.start), end: instant(info.end) },
    title: info.view.title,
    view: viewOfName(info.view.type),
    date: dateIn(instant(info.view.currentStart), timeZone),
  };
}

/** A selection or a click on the grid as the slot to create: timed edges are instants, an
 *  all-day span is dates with an exclusive end. A click selects one slot (or one day), which
 *  is too short to be an event, so it gets the default length. */
export function toSlot(selected: EditedEvent): CreateSlot {
  if (selected.allDay) {
    const start = day(selected.startStr);
    return { allDay: true, start, end: selected.endStr ? day(selected.endStr) : addDays(start, 1) };
  }
  const start = selected.start ? instant(selected.start) : selected.startStr;
  const length =
    selected.end && selected.start ? selected.end.getTime() - selected.start.getTime() : 0;
  const end =
    selected.end && length > SLOT_MINUTES * 60_000
      ? instant(selected.end)
      : Temporal.Instant.from(start).add({ minutes: DEFAULT_CREATE_MINUTES }).toString();
  return { allDay: false, start, end };
}
