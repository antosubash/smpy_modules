import { sharedZone, type TzMode } from '../calendar/time/zones';
import type { CalendarInfo } from '../calendar/types';

export type PublicGridZone = {
  /** What "calendar time" means (and the zone the grid opens on in that mode). */
  defaultTimezone: string;
  tzMode: TzMode;
  /** Whether "calendar time" is offered at all. */
  calendarTime: boolean;
};

/**
 * The zone the public grid opens in, decided in one place so it agrees with the list.
 *
 * The list shows each event on its own clock, and a public calendar's events sit on its default
 * zone, so: calendars that all share one zone open in it ("calendar time", labelled with the zone);
 * calendars that differ have no single zone of their own to offer, so the grid opens on the
 * visitor's own zone and offers only that. The host's default zone is never what a visitor sees.
 */
export function publicGridZone(calendars: CalendarInfo[], hostDefault: string): PublicGridZone {
  const zone = sharedZone(calendars);
  if (zone) return { defaultTimezone: zone, tzMode: 'calendar', calendarTime: true };
  return { defaultTimezone: hostDefault, tzMode: 'mine', calendarTime: false };
}
