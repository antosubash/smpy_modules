/** Time text for the popover and the chips, in a named zone and the console's language. */
import { Temporal } from 'temporal-polyfill';
import type { Occurrence } from '../../utils/types-events';

const instantDate = (iso: string): Date => new Date(Temporal.Instant.from(iso).epochMilliseconds);

/** A calendar date, as the text of that date: no zone is involved, so the formatter runs in
 *  UTC over the date's own midnight. */
function dateText(date: string, locale: string | undefined): string {
  const day = Temporal.PlainDate.from(date);
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(
    new Date(Date.UTC(day.year, day.month - 1, day.day)),
  );
}

function allDayText(o: Occurrence, locale: string | undefined): string {
  const first = o.start_date ?? '';
  // `end_date` is exclusive: the last day shown is the day before it.
  const last = o.end_date
    ? Temporal.PlainDate.from(o.end_date).subtract({ days: 1 }).toString()
    : first;
  return last > first
    ? `${dateText(first, locale)} – ${dateText(last, locale)}`
    : dateText(first, locale);
}

/** Whether the range runs over the autumn change, where the end's clock reads earlier than
 *  (or the same as) the start's: "2:30 – 2:00 AM" for half an hour. */
/** The time in a chip: the start only. On a repeated hour the offset says which pass it is;
 *  the full range stays in the popover. */
export function chipTime(o: Occurrence, timeZone: string, locale: string | undefined): string {
  const ambiguous = readsBackwards(o, timeZone);
  return new Intl.DateTimeFormat(locale, {
    hour: 'numeric',
    minute: '2-digit',
    ...(ambiguous ? { timeZoneName: 'short' as const } : {}),
    timeZone,
  }).format(instantDate(o.start));
}

export function readsBackwards(o: Occurrence, timeZone: string): boolean {
  const wall = (iso: string) =>
    Temporal.Instant.from(iso).toZonedDateTimeISO(timeZone).toPlainDateTime();
  return Temporal.PlainDateTime.compare(wall(o.end), wall(o.start)) <= 0;
}

function zonedText(o: Occurrence, timeZone: string, locale: string | undefined): string {
  if (readsBackwards(o, timeZone)) {
    // Each end names its own offset, so the two clocks are not mistaken for each other.
    const edge = new Intl.DateTimeFormat(locale, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      timeZoneName: 'short',
      timeZone,
    });
    return `${edge.format(instantDate(o.start))} – ${edge.format(instantDate(o.end))}`;
  }
  const format = new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone,
  });
  return format.formatRange(instantDate(o.start), instantDate(o.end));
}

/** The occurrence's time in the grid's zone. An all-day one is dates only and ignores the zone. */
export function timeText(o: Occurrence, timeZone: string, locale: string | undefined): string {
  return o.all_day ? allDayText(o, locale) : zonedText(o, timeZone, locale);
}

/** The event's own local time with its zone name, or `null` when it reads the same in the
 *  grid's zone (or the event is all-day). */
export function localTimeText(
  o: Occurrence,
  gridTimeZone: string,
  locale: string | undefined,
  /** Name the zone after the time; the popover's label already does, so it leaves it off. */
  withZone = true,
): string | null {
  if (o.all_day || o.timezone === gridTimeZone) return null;
  const own = zonedText(o, o.timezone, locale);
  if (own === zonedText(o, gridTimeZone, locale)) return null;
  return withZone ? `${own} (${o.timezone})` : own;
}
