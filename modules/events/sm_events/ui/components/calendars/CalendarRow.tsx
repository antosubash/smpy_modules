import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { TableCell, TableRow } from '@simple-module-py/ui/components/ui/table';
import { usePermissions } from '@simple-module-py/ui/hooks/use-permissions';
import { useState } from 'react';
import { errorText, isGone, restoreCalendar, trashCalendar } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import type { Calendar } from '../../utils/types';
import { ConfirmDialog } from '../ConfirmDialog';
import { ShareDialog } from '../share/ShareDialog';
import { CalendarDialog } from './CalendarDialog';
import { OwnerDialog } from './OwnerDialog';
import { VisibilityMenu } from './VisibilityMenu';

/** A long unbroken name must wrap inside the cell, not widen the table. */
const WRAP = 'max-w-xs whitespace-normal [overflow-wrap:anywhere]';

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
  async function restore() {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      await restoreCalendar(calendar.id);
      onSaved();
    } catch (e) {
      setError(errorText(e, keys.events.errors.calendar_gone));
      if (isGone(e)) onSaved();
    } finally {
      setPending(false);
    }
  }
  return (
    <TableRow>
      <TableCell className={WRAP}>
        <span
          aria-hidden="true"
          className="mr-2 inline-block size-3 rounded-full border"
          style={{ backgroundColor: calendar.color }}
        />
        {calendar.name}
      </TableCell>
      <TableCell className={WRAP}>{calendar.slug}</TableCell>
      <TableCell>
        <Badge variant="outline">{t(keys.events.visibility[calendar.visibility])}</Badge>
      </TableCell>
      <TableCell>{calendar.default_timezone}</TableCell>
      <TableCell>
        {calendar.owner_id === userId
          ? t(copy.you)
          : (calendar.owner_name ?? t(copy.unknown_owner))}
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-2">
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
                    title={t(copy.trash_title, { name: calendar.name })}
                    description={t(copy.trash_description)}
                    confirmLabel={t(copy.trash)}
                    onConfirm={async () => {
                      try {
                        await trashCalendar(calendar.id);
                      } catch (e) {
                        if (isGone(e)) onSaved();
                        throw e;
                      }
                      onSaved();
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
