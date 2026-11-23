/** The default chip. State is written, not coloured: a status word (visually hidden in
 *  month cells, where the border style carries it), struck-through cancelled titles and a
 *  lock with its reason. The title is React text inside `<bdi>`, never markup. */
import { Lock } from 'lucide-react';
import { keys, useT } from '../utils/i18n';
import type { Occurrence } from '../utils/types-events';
import type { EventChipProps } from './types';

export function statusWord(o: Occurrence, t: (key: string) => string): string | null {
  const copy = keys.events.calendar.status;
  if (o.status === 'cancelled') return t(copy.cancelled);
  if (o.event_status === 'draft') return t(copy.draft);
  if (o.event_status === 'in_review') return t(copy.in_review);
  return null;
}

export function EventChip({ occurrence: o, view, timeText, pending, lockReason }: EventChipProps) {
  const { t } = useT();
  const word = statusWord(o, t);
  // A timed block in the week or day grid is a narrow column: time, title and status stack
  // instead of squeezing the title out of a single line.
  // A block under 45 minutes is too short for two lines: it keeps one.
  const long = Date.parse(o.end) - Date.parse(o.start) >= 45 * 60_000;
  const stacked = !o.all_day && (view === 'week' || view === 'day') && long;
  // A short timed block keeps one line with the title first: the time is on the grid's axis
  // and in the accessible name, so it is the first thing to be cut off, not the title.
  const short = !o.all_day && (view === 'week' || view === 'day') && !long;
  const time =
    timeText && !o.all_day ? (
      <span
        className={
          stacked
            ? 'font-medium tabular-nums'
            : short
              ? 'min-w-0 shrink-[4] truncate tabular-nums opacity-80'
              : 'shrink-0 tabular-nums'
        }
      >
        {timeText}
      </span>
    ) : null;
  return (
    <span
      className={
        stacked
          ? 'flex max-h-full min-w-0 flex-col overflow-hidden px-1 text-xs leading-tight'
          : 'flex min-w-0 items-center gap-1 overflow-hidden px-1 text-xs'
      }
      aria-busy={pending ? true : undefined}
    >
      {short ? null : time}
      <span
        data-ev-title
        className={stacked ? 'line-clamp-3 [overflow-wrap:anywhere]' : 'min-w-0 truncate'}
      >
        <bdi>{o.title}</bdi>
      </span>
      {short ? time : null}
      {word ? (
        <span className={view === 'month' ? 'sr-only' : 'shrink-0 font-medium'}>{word}</span>
      ) : null}
      {lockReason ? (
        <Lock
          className="size-3 shrink-0"
          role="img"
          aria-label={`${t(keys.events.calendar.chip.locked)}: ${lockReason}`}
        />
      ) : null}
    </span>
  );
}
