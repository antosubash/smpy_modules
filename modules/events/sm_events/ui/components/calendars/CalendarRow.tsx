import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { TableCell, TableRow } from '@simple-module-py/ui/components/ui/table';
import { useState } from 'react';
import { errorText, restoreCalendar, trashCalendar } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import type { Calendar } from '../../utils/types';
import { ConfirmDialog } from '../ConfirmDialog';
import { ShareDialog } from '../share/ShareDialog';
import { CalendarDialog } from './CalendarDialog';
import { OwnerDialog } from './OwnerDialog';
import { VisibilityMenu } from './VisibilityMenu';

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
      setError(errorText(e));
    } finally {
      setPending(false);
    }
  }
  return (
    <TableRow>
      <TableCell>
        <span
          aria-hidden="true"
          className="mr-2 inline-block size-3 rounded-full border"
          style={{ backgroundColor: calendar.color }}
        />
        {calendar.name}
      </TableCell>
      <TableCell>{calendar.slug}</TableCell>
      <TableCell>
        <Badge variant="outline">{t(keys.events.visibility[calendar.visibility])}</Badge>
      </TableCell>
      <TableCell>{calendar.default_timezone}</TableCell>
      <TableCell>{calendar.owner_id !== userId ? calendar.owner_id : t(copy.you)}</TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-2">
          {trashed ? (
            calendar.can_own && (
              <Button variant="outline" disabled={pending} onClick={() => void restore()}>
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
                />
              )}
              {calendar.can_own && (
                <>
                  <VisibilityMenu calendar={calendar} onSaved={onSaved} />
                  <ShareDialog calendarId={calendar.id} />
                  <ConfirmDialog
                    trigger={<Button variant="outline">{t(copy.trash)}</Button>}
                    title={t(copy.trash_title, { name: calendar.name })}
                    description={t(copy.trash_description)}
                    confirmLabel={t(copy.trash)}
                    onConfirm={async () => {
                      await trashCalendar(calendar.id);
                      onSaved();
                    }}
                  />
                </>
              )}
              {canManage && <OwnerDialog calendarId={calendar.id} onSaved={onSaved} />}
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
