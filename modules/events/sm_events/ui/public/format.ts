/** Text for the public screens that depends on the visitor's own zone. The event's own clock is
 *  formatted by `utils/datetime.ts` (`localSpan`, `daySpan`, `monthName`). */
import { browserZone } from '../utils/zones';

/** The instants in the visitor's own zone, or `null` when it is the event's zone (or the event
 *  is all-day) and the hint would repeat what is already shown. */
export function viewerSpan(
  startIso: string,
  endIso: string,
  eventZone: string,
  locale: string,
  mine: string = browserZone(),
): string | null {
  if (mine === eventZone) return null;
  const format = new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: mine,
  });
  const own = new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: eventZone,
  });
  const a = new Date(startIso);
  const b = new Date(endIso);
  const text = format.formatRange(a, b);
  return text === own.formatRange(a, b) ? null : text;
}
