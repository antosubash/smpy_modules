/** "My reminders": the caller's own follows. A follow on an event the caller can no longer see
 *  is an opaque row (the follow's own id, nothing else) that only offers Remove. */
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { useCallback, useEffect, useState } from 'react';
import { leadsSummary } from '../../reminders/leadText';
import { errorText } from '../../utils/api';
import {
  type MineItem,
  type MinePage,
  myReminders,
  removeFollowById,
} from '../../utils/api-reminders';
import { keys, useT } from '../../utils/i18n';
import { Name } from '../../utils/isolate';
import { EditLeads } from './EditLeads';

const PAGE_SIZE = 20;
/** What one account may follow (the server's cap): the note shows when it is reached. */
const CAP = 200;

export function MyReminders() {
  const { t, locale } = useT();
  const copy = keys.events.reminders.page;
  const [page, setPage] = useState(1);
  const [data, setData] = useState<MinePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const got = await myReminders(page, PAGE_SIZE, signal);
        if (got.items.length === 0 && page > 1) setPage(page - 1);
        else setData(got);
        setError(null);
      } catch (e) {
        if (!signal?.aborted) setError(errorText(e));
      }
    },
    [page],
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const remove = async (item: MineItem) => {
    try {
      await removeFollowById(item.follow_id);
      setNotice(t(copy.removed));
      await load();
    } catch (e) {
      setError(errorText(e));
    }
  };
  const when = (iso: string | null) =>
    iso
      ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(
          new Date(iso),
        )
      : '–';
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const counts = data?.counts;
  const failed = counts ? Object.values(counts.failed).reduce((a, b) => a + b, 0) : 0;

  return (
    <section className="space-y-4" aria-labelledby="mine-heading">
      <h2 id="mine-heading" className="text-lg font-semibold">
        {t(copy.mine)}
      </h2>
      {error ? (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      ) : null}
      {notice ? <p role="status">{notice}</p> : null}
      {data === null && !error ? <p role="status">{t(copy.loading)}</p> : null}
      {data && data.items.length === 0 ? <p>{t(copy.empty)}</p> : null}
      {data && data.items.length > 0 ? (
        <div className="max-w-full overflow-x-auto">
          <Table aria-label={t(copy.mine)}>
            <TableHeader>
              <TableRow>
                <TableHead>{t(copy.col_event)}</TableHead>
                <TableHead className="hidden sm:table-cell">{t(copy.col_calendar)}</TableHead>
                <TableHead className="hidden sm:table-cell">{t(copy.col_next)}</TableHead>
                <TableHead>{t(copy.col_leads)}</TableHead>
                <TableHead>{t(copy.col_actions)}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((item) => (
                <Row
                  key={item.follow_id}
                  item={item}
                  when={when}
                  editing={editing === item.follow_id}
                  onEdit={() => setEditing(item.follow_id)}
                  onClose={() => setEditing(null)}
                  onSaved={() => {
                    setEditing(null);
                    void load();
                  }}
                  onRemove={() => void remove(item)}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
      {data && pages > 1 ? (
        <nav aria-label={t(copy.paging, { page, pages })} className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            {t(copy.previous)}
          </Button>
          <span>{t(copy.paging, { page, pages })}</span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= pages}
            onClick={() => setPage(page + 1)}
          >
            {t(copy.next)}
          </Button>
        </nav>
      ) : null}
      {data && data.hidden > 0 ? (
        <p className="text-sm text-muted-foreground">{t(copy.hidden_note)}</p>
      ) : null}
      {data && data.total >= CAP ? (
        <p role="status" className="text-sm text-muted-foreground">
          {t(copy.cap_note, { count: CAP })}
        </p>
      ) : null}
      {counts ? (
        <p className="text-sm" data-testid="my-counts">
          {t(copy.my_counts, { sent: counts.sent, failed, unfinished: counts.unfinished })}
        </p>
      ) : null}
      <p className="text-sm text-muted-foreground">{t(copy.zone, { zone })}</p>
      <p className="text-sm text-muted-foreground">{t(copy.not_retried)}</p>
      <p className="text-sm text-muted-foreground">{t(copy.scheduler)}</p>
    </section>
  );
}

function Row({
  item,
  when,
  editing,
  onEdit,
  onClose,
  onSaved,
  onRemove,
}: {
  item: MineItem;
  when: (iso: string | null) => string;
  editing: boolean;
  onEdit: () => void;
  onClose: () => void;
  onSaved: () => void;
  onRemove: () => void;
}) {
  const { t, locale } = useT();
  const copy = keys.events.reminders.page;
  if (item.hidden) {
    return (
      <TableRow data-testid="hidden-follow">
        <TableCell className="text-muted-foreground">{t(copy.hidden_event)}</TableCell>
        <TableCell className="hidden sm:table-cell" />
        <TableCell className="hidden sm:table-cell" />
        <TableCell />
        <TableCell>
          <Button
            variant="outline"
            size="sm"
            aria-label={t(copy.remove_for, { name: t(copy.hidden_event) })}
            onClick={onRemove}
          >
            {t(copy.remove)}
          </Button>
        </TableCell>
      </TableRow>
    );
  }
  const title = item.title ?? '';
  return (
    <TableRow>
      <TableCell className="min-w-48 max-w-xs whitespace-normal [overflow-wrap:anywhere]">
        <Name>{title}</Name>
        {item.lang && locale && item.lang !== locale.split('-')[0] ? (
          <span className="ml-2 rounded border px-1 text-xs uppercase" aria-hidden="true">
            {item.lang}
          </span>
        ) : null}
        {!item.deliverable ? (
          <p className="text-xs text-destructive">{t(keys.events.errors.reminders_no_access)}</p>
        ) : null}
      </TableCell>
      <TableCell className="hidden sm:table-cell">
        {item.calendar ? (
          <>
            <span
              aria-hidden="true"
              className="mr-2 inline-block size-3 rounded-sm border"
              style={{ backgroundColor: item.calendar.color }}
            />
            <Name>{item.calendar.name}</Name>
          </>
        ) : null}
      </TableCell>
      <TableCell className="hidden sm:table-cell">{when(item.next_start)}</TableCell>
      <TableCell>
        {editing && item.event_id ? (
          <EditLeads
            eventId={item.event_id}
            leads={item.leads}
            onSaved={onSaved}
            onClose={onClose}
          />
        ) : (
          leadsSummary(t, item.leads)
        )}
      </TableCell>
      <TableCell>
        <div className="flex gap-2 whitespace-nowrap">
          <Button
            variant="outline"
            size="sm"
            aria-label={t(copy.edit_for, { name: title })}
            onClick={onEdit}
          >
            {t(copy.edit)}
          </Button>
          <Button
            variant="outline"
            size="sm"
            aria-label={t(copy.remove_for, { name: title })}
            onClick={onRemove}
          >
            {t(copy.remove)}
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}
