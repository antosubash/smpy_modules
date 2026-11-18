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
  return (
    <span
      className="flex min-w-0 items-center gap-1 px-1 text-xs"
      aria-busy={pending ? true : undefined}
    >
      {timeText && !o.all_day ? <span className="shrink-0 tabular-nums">{timeText}</span> : null}
      <span data-ev-title className="truncate">
        <bdi>{o.title}</bdi>
      </span>
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
