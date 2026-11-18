/** A grid change becomes the request the events API takes. Pure: no fetch, no React.
 *
 *  The grid works in its own zone, but the API takes local wall clock in the *event's* zone,
 *  so every timed edge goes grid wall time -> instant -> event-zone wall time, and an
 *  all-day edge is date arithmetic that no zone touches. Two things the server cannot
 *  represent are refused here, before anything is sent: the second pass through a repeated
 *  autumn hour (the server reads its wall clock as the first) and a wall time the clocks
 *  skip. */
import type { EventDetail, Occurrence, TimesInput } from '../../utils/types-events';
import {
  addDays,
  dateIn,
  daysBetween,
  isNonexistent,
  isRepeatedSecond,
  millisBetween,
  plusMillis,
  sameInstant,
  sameTimeOfDay,
  shiftLocal,
  toLocal,
} from '../time/zones';
import type { OccurrenceChange } from '../types';

export type Scope = 'one' | 'all';
export type Refusal = 'stale' | 'repeated_local_time' | 'invalid_local_time';
export type PatchBody = {
  expected_revision: number;
  times: TimesInput;
  drop_orphaned_overrides?: true;
};
export type OverrideBody = {
  expected_revision: number;
  original_start: string;
  kind: 'moved';
  start: string;
  end: string;
};
export type Plan =
  | { kind: 'patch'; eventId: string; body: PatchBody }
  | { kind: 'override'; eventId: string; body: OverrideBody }
  | { kind: 'refuse'; code: Refusal };

const refuse = (code: Refusal): Plan => ({ kind: 'refuse', code });

/** An occurrence of a series (a one-off has no original start). */
export const isSeries = (o: Occurrence): boolean => o.original_start !== null;

/** Whether the event no longer is what the grid showed. An occurrence carries no revision,
 *  so a write first reads the event and stops here when it differs: "stale" keeps meaning
 *  "changed since you looked", and the revision it then sends is one it just saw. */
export function isStale(o: Occurrence, event: EventDetail): boolean {
  if (event.all_day !== o.all_day || event.timezone !== o.timezone) return true;
  if (!isSeries(o)) return oneOffDiffers(o, event);
  return event.rrule === null || instanceDiffers(o, event);
}

function oneOffDiffers(o: Occurrence, event: EventDetail): boolean {
  if (event.cancelled !== (o.status === 'cancelled')) return true;
  if (o.all_day) {
    return event.start_local !== o.start_date || event.end_local !== addDays(o.end_date ?? '', -1);
  }
  return !sameInstant(event.starts_at, o.start) || !sameInstant(event.ends_at, o.end);
}

function instanceDiffers(o: Occurrence, event: EventDetail): boolean {
  const slot = o.original_start ?? '';
  const override = event.overrides.find((x) => sameInstant(x.original_start, slot));
  if (override) {
    if (override.kind !== 'moved' || !override.starts_at || !override.ends_at) return true;
    if (!o.all_day) {
      return !sameInstant(override.starts_at, o.start) || !sameInstant(override.ends_at, o.end);
    }
    return (
      override.start_local !== o.start_date || addDays(override.end_local ?? '', 1) !== o.end_date
    );
  }
  const zone = event.timezone;
  if (o.all_day) {
    return (
      dateIn(slot, zone) !== o.start_date ||
      daysBetween(o.start_date ?? '', o.end_date ?? '') !==
        daysBetween(event.start_local, event.end_local) + 1
    );
  }
  return (
    !sameInstant(o.start, slot) ||
    millisBetween(o.start, o.end) !== millisBetween(event.starts_at, event.ends_at) ||
    !sameTimeOfDay(toLocal(slot, zone), event.start_local)
  );
}

type Edge = { start: string; end: string };

/** The occurrence's new edges, as the user meant them: instants (timed) or dates with an
 *  exclusive end (all day). A move keeps the exact length; a resize keeps the start. */
function newEdges(change: OccurrenceChange): Edge {
  const o = change.occurrence;
  if (change.kind === 'reschedule') return { start: change.start, end: change.end };
  if (o.all_day) {
    const start = o.start_date ?? change.start;
    if (change.kind === 'resize') return { start, end: change.end };
    const length = daysBetween(start, o.end_date ?? start);
    return { start: change.start, end: addDays(change.start, length) };
  }
  if (change.kind === 'resize') return { start: o.start, end: change.end };
  return { start: change.start, end: plusMillis(change.start, millisBetween(o.start, o.end)) };
}

/** The wall clock of an instant in the event's zone, or the reason it cannot be sent. */
function wall(instant: string, zone: string): string | Refusal {
  return isRepeatedSecond(instant, zone) ? 'repeated_local_time' : toLocal(instant, zone);
}
const isRefusal = (value: string): value is Refusal =>
  value === 'repeated_local_time' || value === 'invalid_local_time' || value === 'stale';

function timedTimes(edge: Edge, event: EventDetail): TimesInput | Refusal {
  const start = wall(edge.start, event.timezone);
  const end = wall(edge.end, event.timezone);
  if (isRefusal(start)) return start;
  if (isRefusal(end)) return end;
  return { all_day: false, timezone: event.timezone, start, end };
}

/** "All occurrences": the user's action is two deltas measured against the instance as it
 *  was displayed (its start and end, an earlier override included), and the master's local
 *  start and end move by those. A move shifts both by the drag; a resize only the end; a
 *  reschedule each edge by what the dialog changed. Timed deltas are wall clock in the
 *  event's zone, so a weekly 10:00 stays a weekly 10:00 across a clock change; all-day ones
 *  are whole days. The rule is never rewritten; a change it cannot hold comes back as
 *  `start_not_in_rule`. */
function masterTimes(
  change: OccurrenceChange,
  edge: Edge,
  event: EventDetail,
): TimesInput | Refusal {
  const o = change.occurrence;
  const zone = event.timezone;
  const move = change.kind === 'move';
  if (o.all_day) {
    const startDays = daysBetween(o.start_date ?? edge.start, edge.start);
    const endDays = move ? startDays : daysBetween(o.end_date ?? edge.end, edge.end);
    return {
      all_day: true,
      timezone: zone,
      start: addDays(event.start_local, startDays),
      end: addDays(event.end_local, endDays),
    };
  }
  const was = { start: toLocal(o.start, zone), end: toLocal(o.end, zone) };
  const to = {
    start: sameInstant(edge.start, o.start) ? was.start : wall(edge.start, zone),
    end: move || sameInstant(edge.end, o.end) ? was.end : wall(edge.end, zone),
  };
  if (isRefusal(to.start)) return to.start;
  if (isRefusal(to.end)) return to.end;
  const start = shiftLocal(event.start_local, was.start, to.start);
  const end = move
    ? shiftLocal(event.end_local, was.start, to.start)
    : shiftLocal(event.end_local, was.end, to.end);
  if (isNonexistent(start, zone) || isNonexistent(end, zone)) return 'invalid_local_time';
  return { all_day: false, timezone: zone, start, end };
}

export function planChange(change: OccurrenceChange, event: EventDetail, scope: Scope): Plan {
  const o = change.occurrence;
  if (change.allDay !== o.all_day) return refuse('stale');
  const edge = newEdges(change);
  const series = isSeries(o);
  const eventId = event.id;
  const expected_revision = event.revision;
  const times =
    series && scope === 'all'
      ? masterTimes(change, edge, event)
      : o.all_day
        ? { all_day: true, timezone: event.timezone, start: edge.start, end: addDays(edge.end, -1) }
        : timedTimes(edge, event);
  if (typeof times === 'string') return refuse(times);
  if (series && scope === 'one') {
    const { start, end } = times;
    return {
      kind: 'override',
      eventId,
      body: {
        expected_revision,
        original_start: o.original_start ?? '',
        kind: 'moved',
        start,
        end,
      },
    };
  }
  return { kind: 'patch', eventId, body: { expected_revision, times } };
}
