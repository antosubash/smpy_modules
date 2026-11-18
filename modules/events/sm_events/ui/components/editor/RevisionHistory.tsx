import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@simple-module-py/ui/components/ui/sheet';
import { useEffect, useState } from 'react';
import { useLatestRequest } from '../../hooks/useLatestRequest';
import { errorText } from '../../utils/api';
import { getRevision, listRevisions } from '../../utils/api-events';
import { formatInstant } from '../../utils/datetime';
import { keys, useT } from '../../utils/i18n';
import { Name } from '../../utils/isolate';
import type { Revision, RevisionDetail } from '../../utils/types-events';

/** The snapshot's own words: its title in the first language it has, and when. */
function SnapshotView({ detail, locale }: { detail: RevisionDetail; locale?: string }) {
  const { t } = useT();
  const copy = keys.events.history;
  const s = detail.snapshot as {
    status?: string;
    timezone?: string;
    starts_at?: string;
    ends_at?: string;
    cancelled?: boolean;
    texts?: Record<string, { title?: string }>;
  };
  const zone = s.timezone ?? 'UTC';
  const title = Object.values(s.texts ?? {})[0]?.title ?? '';
  return (
    <dl
      className="grid gap-1 rounded-md border bg-muted p-3 text-sm"
      aria-label={t(copy.snapshot, { number: detail.number })}
    >
      <dt className="font-medium">{t(copy.snapshot_title)}</dt>
      <dd>{title ? <Name>{title}</Name> : t(keys.events.list.untitled)}</dd>
      <dt className="font-medium">{t(copy.snapshot_when)}</dt>
      <dd>
        {s.starts_at ? formatInstant(s.starts_at, zone, locale) : '–'} –{' '}
        {s.ends_at ? formatInstant(s.ends_at, zone, locale) : '–'} ({zone})
      </dd>
      <dt className="font-medium">{t(copy.snapshot_status)}</dt>
      <dd>
        {s.status && s.status in STATUS
          ? t(STATUS[s.status as keyof typeof STATUS])
          : (s.status ?? '–')}
        {s.cancelled ? ` · ${t(keys.events.list.cancelled)}` : ''}
      </dd>
    </dl>
  );
}

const STATUS = {
  draft: keys.events.list.status_draft,
  in_review: keys.events.list.status_in_review,
  published: keys.events.list.status_published,
} as const;
const ACTIONS: Record<string, string> = {
  created: keys.events.history.action_created,
  updated: keys.events.history.action_updated,
  override_set: keys.events.history.action_override_set,
  override_cleared: keys.events.history.action_override_cleared,
  submitted: keys.events.history.action_submitted,
  withdrawn: keys.events.history.action_withdrawn,
  approved: keys.events.history.action_approved,
  scheduled: keys.events.history.action_scheduled,
  unscheduled: keys.events.history.action_unscheduled,
  rejected: keys.events.history.action_rejected,
  unpublished: keys.events.history.action_unpublished,
  published_scheduled: keys.events.history.action_published_scheduled,
  trashed: keys.events.history.action_trashed,
  restored: keys.events.history.action_restored,
};

function HistoryList({
  eventId,
  timezone,
  revision,
}: {
  eventId: string;
  timezone: string;
  revision: number;
}) {
  const { t, locale } = useT();
  const copy = keys.events.history;
  const [rows, setRows] = useState<Revision[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<RevisionDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const begin = useLatestRequest();
  const beginDetail = useLatestRequest();
  // biome-ignore lint/correctness/useExhaustiveDependencies: a new revision reloads the list
  useEffect(() => {
    const request = begin();
    setError(null);
    listRevisions(eventId, request.signal)
      .then((list) => request.alive() && setRows([...list].sort((a, b) => b.number - a.number)))
      .catch((e) => {
        if (!request.alive()) return;
        setRows(null);
        setError(errorText(e, keys.events.errors.event_gone));
      });
  }, [eventId, revision, begin]);
  function view(number: number) {
    const request = beginDetail();
    setDetailError(null);
    getRevision(eventId, number, request.signal)
      .then((found) => request.alive() && setDetail(found))
      .catch((e) => request.alive() && setDetailError(errorText(e, keys.events.errors.event_gone)));
  }
  return (
    <div className="grid gap-3 overflow-y-auto px-4 pb-4">
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
      {!rows && !error && <p role="status">{t(keys.events.common.loading)}</p>}
      {rows?.length === 0 && <p>{t(copy.empty)}</p>}
      <ol className="grid gap-3">
        {rows?.map((row) => (
          <li key={row.number} className="grid gap-1 border-b pb-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <strong>{t(copy.number, { number: row.number })}</strong>
              <span>{ACTIONS[row.action] ? t(ACTIONS[row.action] as string) : row.action}</span>
              <Button
                variant="outline"
                size="sm"
                className="ml-auto"
                aria-label={t(copy.view_for, { number: row.number })}
                onClick={() => view(row.number)}
              >
                {t(copy.view)}
              </Button>
            </div>
            <span className="text-muted-foreground">
              {row.is_self ? (
                t(copy.actor_you)
              ) : row.actor_name ? (
                <Name>{row.actor_name}</Name>
              ) : row.system || row.actor === null ? (
                t(copy.actor_system)
              ) : (
                t(copy.actor_unknown)
              )}{' '}
              · {formatInstant(row.created_at, timezone, locale)}
            </span>
            {row.note && (
              <span>
                <Name>{row.note}</Name>
              </span>
            )}
            {detail?.number === row.number && <SnapshotView detail={detail} locale={locale} />}
          </li>
        ))}
      </ol>
      {detailError && (
        <p role="alert" className="text-destructive">
          {detailError}
        </p>
      )}
    </div>
  );
}

/** A drawer with the event's revisions, newest first. Read-only: there is no restore. */
export function RevisionHistory({
  eventId,
  timezone,
  revision,
}: {
  eventId: string;
  timezone: string;
  revision: number;
}) {
  const { t } = useT();
  const copy = keys.events.history;
  const [open, setOpen] = useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="outline">{t(copy.button)}</Button>
      </SheetTrigger>
      <SheetContent showCloseButton={false} className="overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{t(copy.title)}</SheetTitle>
          <SheetDescription>{t(copy.description)}</SheetDescription>
        </SheetHeader>
        {open && <HistoryList eventId={eventId} timezone={timezone} revision={revision} />}
        <div className="px-4 pb-4">
          <SheetClose asChild>
            <Button variant="outline">{t(keys.events.common.close)}</Button>
          </SheetClose>
        </div>
      </SheetContent>
    </Sheet>
  );
}
