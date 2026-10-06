import { Head, Link, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';

import { SnapshotList } from '../components/snapshots/SnapshotList';
import { UploadBundleDialog } from '../components/snapshots/UploadBundleDialog';
import { useSnapshots } from '../hooks/useSnapshots';
import { keys, useT } from '../utils/i18n';
import type { PendingImport, Snapshot } from '../utils/snapshotsApi';

interface Props {
  snapshots: Snapshot[];
  pending: PendingImport | null;
}

/**
 * Import / Export — the site's restore points.
 *
 * A snapshot holds every page, redirect, the site layout and the media
 * library. It deliberately does not hold branding or another module's content:
 * pagebuilder does not depend on those, and a snapshot that quietly reached
 * across module boundaries would restore things its owner never chose to
 * capture.
 */
function ContentSnapshots() {
  const { t } = useT();
  const { snapshots, pending } = usePage<{ props: Props }>().props as unknown as Props;
  const state = useSnapshots(snapshots, pending);

  return (
    <>
      <Head title={t(keys.pagebuilder.snapshots.title)} />
      <PageShell
        title={t(keys.pagebuilder.snapshots.title)}
        description={t(keys.pagebuilder.snapshots.description)}
        actions={
          <div className="flex items-center gap-2">
            <UploadBundleDialog
              trigger={<Button variant="outline">{t(keys.pagebuilder.snapshots.upload)}</Button>}
              onUploaded={state.reload}
            />
            <Button disabled={state.busy} onClick={() => void state.take()}>
              {t(keys.pagebuilder.snapshots.take)}
            </Button>
          </div>
        }
      >
        {state.pending && (
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-300 bg-amber-50 p-4">
            <div>
              <p className="font-medium text-amber-900">
                {t(keys.pagebuilder.snapshots.pending_title)}
              </p>
              <p className="text-sm text-amber-800">
                {t(keys.pagebuilder.snapshots.pending_description)}
              </p>
            </div>
            <Button asChild>
              <Link href="/pagebuilder/content/review">
                {t(keys.pagebuilder.snapshots.pending_review)}
              </Link>
            </Button>
          </div>
        )}

        {state.error && <p className="mb-4 text-sm text-destructive">{state.error}</p>}

        <SnapshotList
          snapshots={state.snapshots}
          busy={state.busy}
          hasPending={state.pending !== null}
          pendingSnapshotId={state.pending?.snapshot_id ?? null}
          onRestore={state.restore}
          onDelete={state.remove}
        />

        <p className="mt-6 text-xs text-muted-foreground">
          {t(keys.pagebuilder.snapshots.footnote)}
        </p>
      </PageShell>
    </>
  );
}

ContentSnapshots.layout = [AuthenticatedLayout];
export default ContentSnapshots;
