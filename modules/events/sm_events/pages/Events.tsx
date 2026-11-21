import { Head, router } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useState } from 'react';
import { EventFilters } from '../ui/components/events/EventFilters';
import { type CalendarChoice, EventRow } from '../ui/components/events/EventRow';
import { useEvents } from '../ui/hooks/useEvents';
import { keys, useT } from '../ui/utils/i18n';
import type { Category } from '../ui/utils/types';

type Props = {
  content_locales: string[];
  can_create: boolean;
  categories: Category[];
  calendars: CalendarChoice[];
};

const NEW_EVENT = '/admin/events/edit/new';

export default function Events({ content_locales, can_create, categories, calendars }: Props) {
  const { t, locale } = useT();
  const copy = keys.events.list;
  const language = locale?.split('-')[0];
  // The language titles are asked in: the console's, when it is a content language.
  const requested =
    language && content_locales.includes(language) ? language : (content_locales[0] ?? 'en');
  const list = useEvents(requested);
  const writable = calendars.filter((c) => c.can_write_events);
  const [target, setTarget] = useState(writable[0]?.id ?? '');
  const byId = new Map(calendars.map((c) => [c.id, c]));
  const pages = Math.max(1, Math.ceil(list.total / list.pageSize));
  const nothing = !list.loading && !list.error && list.items.length === 0;
  const order = [...new Set([requested, ...content_locales])];
  return (
    <>
      <Head title={t(copy.title)} />
      <PageShell
        title={t(copy.title)}
        description={t(copy.subtitle)}
        actions={
          can_create && writable.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              {writable.length > 1 && (
                <NativeSelect
                  className="max-w-full"
                  aria-label={t(copy.new_calendar)}
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                >
                  {writable.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </NativeSelect>
              )}
              <Button onClick={() => router.visit(`${NEW_EVENT}?calendar=${target}`)}>
                {t(copy.new)}
              </Button>
            </div>
          ) : undefined
        }
      >
        <div className="min-w-0 space-y-4">
          <EventFilters
            filters={list.filters}
            calendars={calendars}
            categories={categories}
            locales={order}
            onChange={list.change}
          />
          <fieldset className="flex min-w-0 flex-wrap gap-2" aria-label={t(copy.view_filter)}>
            {[false, true].map((trash) => (
              <Button
                key={String(trash)}
                variant={list.filters.trash === trash ? 'default' : 'outline'}
                aria-pressed={list.filters.trash === trash}
                onClick={() => list.change({ trash })}
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
                    copy.col_title,
                    copy.col_calendar,
                    copy.col_starts,
                    copy.col_status,
                    copy.col_actions,
                  ].map((key) => (
                    <TableHead key={key}>{t(key)}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.items.map((event) => (
                  <EventRow
                    key={event.id}
                    event={event}
                    calendar={byId.get(event.calendar_id)}
                    trashed={list.filters.trash}
                    requested={requested}
                    onChanged={list.reload}
                  />
                ))}
              </TableBody>
            </Table>
          </div>
          {nothing && <p>{t(list.filters.trash ? copy.empty_trash : copy.empty)}</p>}
          {!list.error && list.total > 0 && (
            <nav
              className="flex items-center gap-3"
              aria-label={t(copy.page, { page: list.filters.page, pages })}
            >
              <Button
                variant="outline"
                disabled={list.filters.page <= 1}
                onClick={() => list.setPage(list.filters.page - 1)}
              >
                {t(copy.previous)}
              </Button>
              <span>{t(copy.page, { page: list.filters.page, pages })}</span>
              <Button
                variant="outline"
                disabled={list.filters.page >= pages}
                onClick={() => list.setPage(list.filters.page + 1)}
              >
                {t(copy.next)}
              </Button>
              <span className="text-muted-foreground">{t(copy.total, { count: list.total })}</span>
            </nav>
          )}
        </div>
      </PageShell>
    </>
  );
}
Events.layout = [AuthenticatedLayout];
