import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useEffect, useRef } from 'react';
import { Announce } from '../ui/components/import/Announce';
import { ImportProgress } from '../ui/components/import/ImportProgress';
import { ImportResult } from '../ui/components/import/ImportResult';
import { PreviewTable } from '../ui/components/import/PreviewTable';
import { type TargetCalendar, UploadForm } from '../ui/components/import/UploadForm';
import { useImport } from '../ui/hooks/useImport';
import { ACTIVE, failureText } from '../ui/utils/api-import';
import { keys, useT } from '../ui/utils/i18n';

type Props = {
  calendars: TargetCalendar[];
  can_publish: boolean;
  max_bytes: number;
  import_id: number | null;
};

/** Upload an `.ics`, see what will happen to each event, then import it. The server decides
 *  everything (the file, the rights, the limits); this screen shows its answers. */
export default function Import({ calendars, can_publish, max_bytes, import_id }: Props) {
  const { t } = useT();
  const copy = keys.events.import;
  const state = useImport(import_id);
  const { row } = state;
  const step = useRef<HTMLDivElement>(null);
  const stage =
    row?.status === 'staged' || row?.status === 'done' || row?.status === 'failed'
      ? row.status
      : null;
  // A new step replaces the part of the page that had focus: move focus to its heading.
  useEffect(() => {
    if (stage === null) return;
    const heading = step.current?.querySelector<HTMLElement>('h2');
    heading?.setAttribute('tabindex', '-1');
    heading?.focus();
  }, [stage]);
  return (
    <>
      <Head title={t(copy.title)} />
      <PageShell title={t(copy.title)} description={t(copy.subtitle)}>
        <div className="space-y-4" ref={step}>
          <Announce row={row} uploading={state.busy && !row} />
          {state.error && (
            <p role="alert" className="text-destructive">
              {state.error}
            </p>
          )}
          {state.waiting.length > 0 && (
            <section aria-label={t(copy.waiting_title)} className="space-y-1">
              <h2 className="text-sm font-medium">{t(copy.waiting_title)}</h2>
              <ul className="list-disc pl-5 text-sm">
                {state.waiting.map((w) => (
                  <li key={w.id}>
                    <a className="underline" href={`${window.location.pathname}?id=${w.id}`}>
                      {w.filename} · {w.calendar.name}
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {!row && state.id === null && (
            <UploadForm
              calendars={calendars}
              maxBytes={max_bytes}
              busy={state.busy}
              onUpload={(calendarId, file) => void state.upload(calendarId, file)}
            />
          )}
          {row && ACTIVE.includes(row.status) && <ImportProgress row={row} />}
          {row?.status === 'staged' && (
            <PreviewTable
              row={row}
              page={state.items}
              filter={state.filter}
              setFilter={state.setFilter}
              canPublish={can_publish}
              busy={state.busy}
              onApply={(publish) => void state.apply(publish)}
              onDiscard={() => void state.discard()}
            />
          )}
          {row?.status === 'done' && (
            <ImportResult
              row={row}
              page={state.items}
              filter={state.filter}
              setFilter={state.setFilter}
              onDiscard={() => void state.discard()}
            />
          )}
          {row?.status === 'failed' && (
            <section className="space-y-3" aria-label={t(copy.failed_title)}>
              <h2 className="text-lg font-medium">{t(copy.failed_title)}</h2>
              <p role="alert">{failureText(row.error_code)}</p>
              <Button type="button" onClick={() => void state.discard()}>
                {t(copy.start_again)}
              </Button>
            </section>
          )}
        </div>
      </PageShell>
    </>
  );
}
Import.layout = [AuthenticatedLayout];
