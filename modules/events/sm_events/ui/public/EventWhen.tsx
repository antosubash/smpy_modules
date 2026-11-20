import { daySpan, localSpan } from '../utils/datetime';
import { keys, useT } from '../utils/i18n';
import { viewerSpan } from './format';
import type { PublicEventProps, When } from './types';

/** The event's own time, and, for a timed event, the visitor's when their zone differs.
 *  An all-day event is dates only and never shifted. */
export function EventWhen({
  when,
  timezone,
  locale,
}: Pick<PublicEventProps, 'timezone' | 'locale'> & { when: When }) {
  const { t } = useT();
  const copy = keys.events.public.event;
  const own = when.all_day
    ? daySpan(
        when.start_date ?? when.start_local.slice(0, 10),
        when.end_date ? when.end_local.slice(0, 10) : null,
        locale,
      )
    : `${localSpan(when.start_local, when.end_local, locale)} (${timezone})`;
  const mine = when.all_day ? null : viewerSpan(when.start, when.end, timezone, locale);
  const previous = when.previous_start_local
    ? localSpan(when.previous_start_local, when.previous_start_local, locale)
    : null;
  return (
    <div className="space-y-1">
      <p>
        <time dateTime={when.start_local}>{own}</time>
      </p>
      {mine ? (
        <p className="text-sm text-muted-foreground dark:text-zinc-400">
          {t(copy.your_time, { time: mine })}
        </p>
      ) : null}
      {previous ? (
        <p className="text-sm font-medium">{t(copy.rescheduled_from, { time: previous })}</p>
      ) : null}
    </div>
  );
}
