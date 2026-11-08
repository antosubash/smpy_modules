import { Head, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@simple-module-py/ui/components/ui/alert-dialog';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import type { SharedProps } from '@simple-module-py/ui/types';
import { type ReactNode, useEffect, useRef, useState } from 'react';

import { ImportErrors } from '../ui/components/import/ImportErrors';
import { ImportHistory } from '../ui/components/import/ImportHistory';
import { ImportCounts, ImportProgress } from '../ui/components/import/ImportProgress';
import { ImportSummary } from '../ui/components/import/ImportSummary';
import { ListPicker } from '../ui/components/import/ListPicker';
import { MappingTable } from '../ui/components/import/MappingTable';
import { UploadStep } from '../ui/components/import/UploadStep';
import { useImport } from '../ui/hooks/useImport';
import { codeMessage } from '../ui/utils/http';
import { keys, useT } from '../ui/utils/i18n';
import type { ImportMapping } from '../ui/utils/importTypes';

const copy = keys.newsletter.import;

interface ImportProps {
  lists?: string[];
  initial_import?: number | null;
}

function Step({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

/** Mailchimp import: list, upload, preview and mapping, progress, result. */
export default function Import() {
  const { t } = useT();
  const props = usePage<{ props: SharedProps & ImportProps }>().props as unknown as SharedProps &
    ImportProps;
  const { job, error, busy, upload, saveMapping, apply, discard, open, reset } = useImport(
    props.initial_import ?? null,
  );
  const [lists, setLists] = useState<string[]>(props.lists ?? []);
  const [listKey, setListKey] = useState(props.lists?.[0] ?? '');
  const [mapping, setMapping] = useState<ImportMapping>({ fields: {}, tags: false });
  const [confirming, setConfirming] = useState(false);
  // Held across the save and the apply, between which `busy` drops for a moment.
  const [starting, setStarting] = useState(false);
  const startingNow = useRef(false); // a second click in the same tick sees the state unchanged

  const jobId = job?.id ?? null;
  const staged = job?.status === 'staged';
  // A newly opened staged job starts from the mapping the server proposed.
  // biome-ignore lint/correctness/useExhaustiveDependencies: only a different job resets it
  useEffect(() => {
    if (job?.status !== 'staged') return;
    setMapping({
      fields: job.mapping.fields ?? {},
      tags: job.targets.tags !== 'missing' && (job.mapping.tags ?? false),
    });
  }, [jobId, staged]);

  const created = (key: string) => {
    setLists((all) => (all.includes(key) ? all : [...all, key].sort()));
    setListKey(key);
  };
  const start = async () => {
    if (startingNow.current) return;
    startingNow.current = true;
    setStarting(true);
    try {
      if (await saveMapping(mapping)) await apply();
    } finally {
      startingNow.current = false;
      setStarting(false);
    }
  };

  return (
    <PageShell title={t(copy.title)} description={t(copy.description)}>
      <Head title={t(copy.title)} />
      <div className="grid gap-4">
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        {job === null && (
          <>
            <Step title={t(copy.list_label)}>
              {lists.length === 0 && (
                <p className="mb-3 text-sm text-muted-foreground">{t(copy.no_lists)}</p>
              )}
              <ListPicker
                lists={lists}
                value={listKey}
                disabled={busy}
                onChange={setListKey}
                onCreated={created}
              />
            </Step>
            <Step title={t(copy.upload_label)}>
              <UploadStep
                disabled={listKey === ''}
                busy={busy}
                onUpload={(files) => void upload(listKey, files)}
              />
            </Step>
          </>
        )}

        {job !== null && staged && (
          <>
            <Step title={t(copy.files)}>
              <ImportSummary job={job} />
            </Step>
            <Step title={t(copy.mapping_title)}>
              <MappingTable
                columns={job.columns}
                targets={job.targets}
                mapping={mapping}
                tagsFound={job.tags_found}
                onChange={setMapping}
              />
            </Step>
            <div className="flex gap-2">
              <Button
                type="button"
                disabled={busy || starting || job.total === 0}
                onClick={() => void start()}
              >
                {busy || starting ? t(copy.applying) : t(copy.apply)}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={busy || starting}
                onClick={() => setConfirming(true)}
              >
                {t(copy.discard)}
              </Button>
            </div>
            {job.total === 0 && <p className="text-sm text-muted-foreground">{t(copy.no_rows)}</p>}
          </>
        )}

        {job !== null && (job.status === 'queued' || job.status === 'running') && (
          <Step title={t(copy.status.running)}>
            <ImportProgress job={job} />
          </Step>
        )}

        {job !== null && (job.status === 'done' || job.status === 'failed') && (
          <Step title={job.status === 'done' ? t(copy.done) : t(copy.failed)}>
            <div className="grid gap-4">
              {job.status === 'failed' && (
                <p role="alert" className="text-sm text-destructive">
                  {codeMessage(job.error_code, t)}
                </p>
              )}
              <ImportCounts job={job} />
              <ImportErrors job={job} />
              <div className="flex gap-2">
                {job.status === 'failed' && (
                  <Button type="button" disabled={busy} onClick={() => void apply()}>
                    {t(copy.apply_again)}
                  </Button>
                )}
                <Button type="button" variant="outline" onClick={reset}>
                  {t(copy.another)}
                </Button>
              </div>
            </div>
          </Step>
        )}

        <Step title={t(copy.history)}>
          <ImportHistory refreshKey={`${jobId}:${job?.status}`} onOpen={open} />
        </Step>
      </div>

      {confirming && (
        <AlertDialog open onOpenChange={(o) => !o && setConfirming(false)}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t(copy.discard_confirm.title)}</AlertDialogTitle>
              <AlertDialogDescription>{t(copy.discard_confirm.description)}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t(copy.discard_confirm.keep)}</AlertDialogCancel>
              <AlertDialogAction
                onClick={() => {
                  setConfirming(false);
                  void discard();
                }}
              >
                {t(copy.discard_confirm.confirm)}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </PageShell>
  );
}

Import.layout = [AuthenticatedLayout];
