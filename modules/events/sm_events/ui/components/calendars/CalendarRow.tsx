import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { TableCell, TableRow } from '@simple-module-py/ui/components/ui/table';
import { usePermissions } from '@simple-module-py/ui/hooks/use-permissions';
import { useState } from 'react';
import { toast } from 'sonner';
import { type ScopedRequest, useRequestScope } from '../../hooks/useRequestScope';
import {
  errorText,
  getCalendar,
  isGone,
  listCalendars,
  restoreCalendar,
  trashCalendar,
} from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import { Name, withName } from '../../utils/isolate';
import type { Calendar } from '../../utils/types';
import { ConfirmDialog } from '../ConfirmDialog';
import { ShareDialog } from '../share/ShareDialog';
import { CalendarDialog } from './CalendarDialog';
import { OwnerDialog } from './OwnerDialog';
import { VisibilityMenu } from './VisibilityMenu';

/** Where a calendar is now, after a request found it missing: in the active
 *  list, in the trash, or (`null`) in neither. The lists are capped, so a
 *  calendar in neither is confirmed with one direct read: a trashed calendar
 *  cannot be read by id (it answers 404 to everyone), so only an active one
 *  answers 200. A 404 there means it is gone or no longer visible to this user. */
async function whereIs(id: string): Promise<'active' | 'trash' | null> {
  const [active, trash] = await Promise.all([listCalendars(false), listCalendars(true)]);
  if (active.some((c) => c.id === id)) return 'active';
  if (trash.some((c) => c.id === id)) return 'trash';
  try {
    await getCalendar(id);
    return 'active';
  } catch (e) {
    if (isGone(e)) return null;
    throw e;
  }
}

/** A long unbroken name must wrap inside the cell, not widen the table. */
const WRAP = 'max-w-xs whitespace-normal [overflow-wrap:anywhere]';
/** The name cell keeps a readable width instead of collapsing to one letter per line. */
const NAME = `min-w-48 ${WRAP}`;
// Wide enough that an ordinary slug stays on one line; only a long one wraps.
const SLUG = `min-w-40 ${WRAP}`;

export function CalendarRow({
  calendar,
  userId,
  canManage,
  trashed,
  onSaved,
}: {
  calendar: Calendar;
  userId: string;
  canManage: boolean;
  trashed: boolean;
  onSaved: () => void;
}) {
  const { t } = useT();
  const { can } = usePermissions();
  const copy = keys.events.calendars;
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const begin = useRequestScope(true);
  async function restore() {
    if (pending) return;
    const request = begin();
    setPending(true);
    setError(null);
    try {
      await restoreCalendar(calendar.id);
      if (request.alive()) onSaved();
    } catch (e) {
      await missing(e, 'active', request);
    } finally {
      if (request.alive()) setPending(false);
    }
  }
  /** A 404 from restore or trash. Another tab may simply have done the same
   *  thing already (`already`), which is no error: reload and say nothing.
   *  Only a calendar that is nowhere (see `whereIs`) is gone; the row goes
   *  with the reload, so that message is a toast, not text in the row. */
  async function missing(e: unknown, already: 'active' | 'trash', request: ScopedRequest) {
    if (!request.alive()) return;
    if (!isGone(e)) {
      setError(errorText(e));
      return;
    }
    try {
      const where = await whereIs(calendar.id);
      if (!request.alive()) return;
      onSaved();
      if (where === null) toast.error(t(keys.events.errors.calendar_gone));
      else if (where !== already) setError(errorText(e));
    } catch (check) {
      if (!request.alive()) return;
      onSaved();
      setError(errorText(check));
    }
  }
  return (
    <TableRow>
      <TableCell className={NAME}>
        <span
          aria-hidden="true"
          className="mr-2 inline-block size-3 rounded-full border"
          style={{ backgroundColor: calendar.color }}
        />
        <Name>{calendar.name}</Name>
      </TableCell>
      <TableCell className={SLUG}>{calendar.slug}</TableCell>
      <TableCell>
        <Badge variant="outline">{t(keys.events.visibility[calendar.visibility])}</Badge>
      </TableCell>
      <TableCell>{calendar.default_timezone}</TableCell>
      <TableCell>
        {calendar.owner_id === userId ? (
          t(copy.you)
        ) : calendar.owner_name ? (
          <Name>{calendar.owner_name}</Name>
        ) : (
          t(copy.unknown_owner)
        )}
      </TableCell>
      <TableCell>
        <div className="flex gap-2 whitespace-nowrap">
          {trashed ? (
            calendar.can_own && (
              <Button
                variant="outline"
                disabled={pending}
                aria-label={t(copy.restore_for, { name: calendar.name })}
                onClick={() => void restore()}
              >
                {t(copy.restore)}
              </Button>
            )
          ) : (
            <>
              {calendar.can_edit && (
                <CalendarDialog
                  calendar={calendar}
                  defaultTimezone={calendar.default_timezone}
                  onSaved={onSaved}
                  onGone={onSaved}
                />
              )}
              {calendar.can_own && (
                <>
                  <VisibilityMenu calendar={calendar} onSaved={onSaved} />
                  {can('sharing.share') && (
                    <ShareDialog
                      calendarId={calendar.id}
                      calendarName={calendar.name}
                      onGone={onSaved}
                    />
                  )}
                  <ConfirmDialog
                    trigger={
                      <Button
                        variant="outline"
                        aria-label={t(copy.trash_for, { name: calendar.name })}
                      >
                        {t(copy.trash)}
                      </Button>
                    }
                    title={withName(t, copy.trash_title, calendar.name)}
                    description={t(copy.trash_description)}
                    confirmLabel={t(copy.trash)}
                    onConfirm={async () => {
                      const request = begin();
                      try {
                        await trashCalendar(calendar.id);
                      } catch (e) {
                        // A 404 closes the confirmation: `missing` answers it. Any other
                        // failure stays in the dialog.
                        if (!isGone(e)) throw e;
                        await missing(e, 'trash', request);
                        return;
                      }
                      if (request.alive()) onSaved();
                    }}
                  />
                </>
              )}
              {canManage && (
                <OwnerDialog
                  calendarId={calendar.id}
                  calendarName={calendar.name}
                  onSaved={onSaved}
                />
              )}
            </>
          )}
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
