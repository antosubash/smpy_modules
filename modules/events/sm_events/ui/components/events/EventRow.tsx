import { Link } from '@inertiajs/react';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { TableCell, TableRow } from '@simple-module-py/ui/components/ui/table';
import { useState } from 'react';
import { toast } from 'sonner';
import { useRequestScope } from '../../hooks/useRequestScope';
import { errorText, isGone } from '../../utils/api';
import { restoreEvent, trashEvent } from '../../utils/api-events';
import { browserZone, formatInstant, formatWall } from '../../utils/datetime';
import { keys, useT } from '../../utils/i18n';
import { Name, withName } from '../../utils/isolate';
import { parseRule, summarise } from '../../utils/recurrence';
import type { EventListItem } from '../../utils/types-events';
import { ConfirmDialog } from '../ConfirmDialog';

/** A long unbroken title must wrap inside the cell, not widen the table. */
const WRAP = 'max-w-xs whitespace-normal [overflow-wrap:anywhere]';
const TITLE = `min-w-48 ${WRAP}`;
export const editorUrl = (id: string) => `/admin/events/edit/${id}`;

export type CalendarChoice = {
  id: string;
  name: string;
  color: string;
  default_timezone: string;
  can_write_events: boolean;
};

/** What the caller may do to the event, from the flags the API returns: a
 *  locked (published or scheduled) event needs the publish right as well. */
export const mayChange = (event: EventListItem): boolean =>
  event.can_write && (!event.locked || event.can_publish);

function when(event: EventListItem, locale?: string): string {
  const start = formatWall(event.start_local, locale);
  if (!event.all_day) return start;
  const end = formatWall(event.end_local, locale);
  return end === start ? start : `${start} – ${end}`;
}

export function EventRow({
  event,
  calendar,
  trashed,
  requested,
  onChanged,
}: {
  event: EventListItem;
  calendar?: CalendarChoice;
  trashed: boolean;
  /** The language the list asked titles in; another one is a fallback. */
  requested: string;
  onChanged: () => void;
}) {
  const { t, locale } = useT();
  const copy = keys.events.list;
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const begin = useRequestScope(true);
  const title = event.title || t(copy.untitled);
  const rule = parseRule(event.rrule, event.start_local, event.timezone);
  const summary = rule ? summarise(rule, event.start_local, locale) : null;
  const status = event.scheduled ? 'scheduled' : event.status;

  /** A 404 means the event is gone or no longer visible: refresh, and say so. */
  function gone(request: { alive: () => boolean }) {
    if (!request.alive()) return;
    onChanged();
    toast.error(t(keys.events.errors.event_gone));
  }
  async function restore() {
    if (pending) return;
    const request = begin();
    setPending(true);
    setError(null);
    try {
      await restoreEvent(event.id, event.revision);
      if (request.alive()) onChanged();
    } catch (e) {
      if (!request.alive()) return;
      if (isGone(e)) gone(request);
      else {
        setError(errorText(e));
        onChanged();
      }
    } finally {
      if (request.alive()) setPending(false);
    }
  }
  async function trash() {
    const request = begin();
    try {
      await trashEvent(event.id, event.revision);
    } catch (e) {
      if (!request.alive()) return;
      if (isGone(e)) return gone(request);
      onChanged(); // the next attempt quotes the new revision
      throw e;
    }
    if (request.alive()) onChanged();
  }
  return (
    <TableRow>
      <TableCell className={TITLE}>
        {trashed ? (
          <Name>{title}</Name>
        ) : (
          <Link
            href={editorUrl(event.id)}
            className="font-medium underline-offset-4 hover:underline"
          >
            <Name>{title}</Name>
          </Link>
        )}
        {event.lang && event.lang !== requested && (
          <Badge
            variant="outline"
            className="ml-2"
            aria-label={t(copy.lang_fallback, { lang: event.lang })}
          >
            {event.lang}
          </Badge>
        )}
        {summary && (
          <span
            role="img"
            className="ml-2"
            title={t(copy.recurring, { summary })}
            aria-label={t(copy.recurring, { summary })}
          >
            ↻
          </span>
        )}
      </TableCell>
      <TableCell className={WRAP}>
        {calendar && (
          <>
            <span
              aria-hidden="true"
              className="mr-2 inline-block size-3 rounded-full border"
              style={{ backgroundColor: calendar.color }}
            />
            <Name>{calendar.name}</Name>
          </>
        )}
      </TableCell>
      <TableCell>
        <div>{when(event, locale)}</div>
        {event.all_day && <div className="text-xs text-muted-foreground">{t(copy.all_day)}</div>}
        {event.timezone !== browserZone() && (
          <div className="text-xs text-muted-foreground">{event.timezone}</div>
        )}
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-1">
          <Badge variant={status === 'published' ? 'default' : 'secondary'}>
            {t(keys.events.list[`status_${status}`])}
          </Badge>
          {event.cancelled && <Badge variant="destructive">{t(copy.cancelled)}</Badge>}
        </div>
        {event.scheduled && event.publish_at && (
          <div className="text-xs text-muted-foreground">
            {t(copy.scheduled_for, {
              when: formatInstant(event.publish_at, event.timezone, locale),
            })}
          </div>
        )}
      </TableCell>
      <TableCell>
        <div className="flex gap-2 whitespace-nowrap">
          {!trashed && (
            <Button asChild variant="outline">
              <Link
                href={editorUrl(event.id)}
                aria-label={t(event.can_write ? copy.edit_for : copy.view_for, { title })}
              >
                {t(event.can_write ? copy.edit : copy.open)}
              </Link>
            </Button>
          )}
          {mayChange(event) &&
            (trashed ? (
              <Button
                variant="outline"
                disabled={pending}
                aria-label={t(copy.restore_for, { title })}
                onClick={() => void restore()}
              >
                {t(copy.restore)}
              </Button>
            ) : (
              <ConfirmDialog
                trigger={
                  <Button variant="outline" aria-label={t(copy.trash_for, { title })}>
                    {t(copy.trash)}
                  </Button>
                }
                title={withName(t, copy.trash_title, title)}
                description={t(copy.trash_description)}
                confirmLabel={t(copy.trash)}
                onConfirm={trash}
              />
            ))}
        </div>
        {error && (
          <p role="alert" className="text-destructive">
            {error}
          </p>
        )}
      </TableCell>
    </TableRow>
  );
}
