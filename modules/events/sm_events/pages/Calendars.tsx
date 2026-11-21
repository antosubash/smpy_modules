import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { CalendarDialog } from '../ui/components/calendars/CalendarDialog';
import { CalendarRow } from '../ui/components/calendars/CalendarRow';
import { useCalendars } from '../ui/hooks/useCalendars';
import { keys, useT } from '../ui/utils/i18n';

type Props = {
  can_create: boolean;
  can_manage: boolean;
  user_id: string;
  default_timezone: string;
};
export default function Calendars({ can_create, can_manage, user_id, default_timezone }: Props) {
  const { t } = useT();
  const copy = keys.events.calendars;
  const list = useCalendars();
  return (
    <>
      <Head title={t(copy.title)} />
      <PageShell
        title={t(copy.title)}
        description={t(copy.subtitle)}
        actions={
          can_create ? (
            <CalendarDialog defaultTimezone={default_timezone} onSaved={list.reload} />
          ) : undefined
        }
      >
        <div className="space-y-4">
          <fieldset className="flex gap-2" aria-label={t(copy.filter)}>
            {[false, true].map((trash) => (
              <Button
                key={String(trash)}
                variant={list.trashed === trash ? 'default' : 'outline'}
                aria-pressed={list.trashed === trash}
                onClick={() => list.setTrashed(trash)}
              >
                {t(trash ? copy.trash_tab : copy.active)}
              </Button>
            ))}
          </fieldset>
          {list.error && (
            <p role="alert" className="text-destructive">
              {list.error}
            </p>
          )}
          {list.loading && <p role="status">{t(keys.events.common.loading)}</p>}
          <div className="max-w-full overflow-x-auto">
            <Table aria-label={t(copy.title)}>
              <TableHeader>
                <TableRow>
                  {[
                    copy.name,
                    copy.col_slug,
                    copy.visibility,
                    copy.timezone,
                    copy.owner,
                    copy.actions,
                  ].map((key) => (
                    <TableHead key={key}>{t(key)}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.items.map((calendar) => (
                  <CalendarRow
                    key={calendar.id}
                    calendar={calendar}
                    userId={user_id}
                    canManage={can_manage}
                    trashed={list.trashed}
                    onSaved={list.reload}
                  />
                ))}
              </TableBody>
            </Table>
          </div>
          {!list.loading && !list.error && list.items.length === 0 && <p>{t(copy.empty)}</p>}
        </div>
      </PageShell>
    </>
  );
}
Calendars.layout = [AuthenticatedLayout];
