import { Link } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { formatWall } from '../../utils/datetime';
import { keys, useT } from '../../utils/i18n';
import { Name } from '../../utils/isolate';
import type { SubEvent } from '../../utils/types-events';

const EDIT = '/admin/events/edit';

/** The event's place in a one-level tree: its parent, or its sub-events with a
 *  way to add one. Sub-events and recurrence exclude each other. */
export function SubEvents({
  parentId,
  subEvents,
  calendarId,
  eventId,
  canAdd,
}: {
  parentId: string | null;
  subEvents: SubEvent[];
  calendarId: string;
  eventId: string;
  canAdd: boolean;
}) {
  const { t, locale } = useT();
  const copy = keys.events.editor;
  if (parentId) {
    return (
      <section className="grid gap-2" aria-label={t(copy.sub_events)}>
        <p className="text-sm">{t(copy.is_sub_event)}</p>
        <div>
          <Button asChild variant="outline">
            <Link href={`${EDIT}/${parentId}`}>{t(copy.open_parent)}</Link>
          </Button>
        </div>
      </section>
    );
  }
  if (subEvents.length === 0 && !canAdd) return null;
  return (
    <section className="grid gap-2" aria-label={t(copy.sub_events)}>
      <h3 className="text-sm font-medium">{t(copy.sub_events)}</h3>
      {subEvents.length === 0 && (
        <p className="text-sm text-muted-foreground">{t(copy.no_sub_events)}</p>
      )}
      <ul className="grid gap-1">
        {subEvents.map((sub) => (
          <li key={sub.id} className="text-sm">
            <Link href={`${EDIT}/${sub.id}`} className="underline-offset-4 hover:underline">
              <Name>{sub.title}</Name>
            </Link>{' '}
            <span className="text-muted-foreground">{formatWall(sub.start_local, locale)}</span>
          </li>
        ))}
      </ul>
      {canAdd && (
        <div>
          <Button asChild variant="outline">
            <Link href={`${EDIT}/new?calendar=${calendarId}&parent=${eventId}`}>
              {t(copy.add_sub_event)}
            </Link>
          </Button>
        </div>
      )}
    </section>
  );
}
