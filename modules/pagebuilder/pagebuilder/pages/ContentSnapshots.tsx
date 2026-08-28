import { Head, Link, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';

import { SnapshotList } from '../components/snapshots/SnapshotList';
import { UploadBundleDialog } from '../components/snapshots/UploadBundleDialog';
import { useSnapshots } from '../hooks/useSnapshots';
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
export default function ContentSnapshots() {
  const { snapshots, pending } = usePage<{ props: Props }>().props as unknown as Props;
  const state = useSnapshots(snapshots, pending);

  return (
    <AuthenticatedLayout>
      <Head title="Import / Export" />
      <PageShell
        title="Import / Export"
        description="Snapshot the whole site, move it between hosts, and roll back to any point."
        actions={
          <div className="flex items-center gap-2">
            <UploadBundleDialog
              trigger={<Button variant="outline">Upload bundle…</Button>}
              onUploaded={state.reload}
            />
            <Button disabled={state.busy} onClick={() => void state.take()}>
              Take snapshot
            </Button>
          </div>
        }
      >
        {state.pending && (
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-md border border-amber-300 bg-amber-50 p-4">
            <div>
              <p className="font-medium text-amber-900">A restore is waiting for approval.</p>
              <p className="text-sm text-amber-800">
                Nothing has changed on the site yet. Someone with approval rights has to apply it.
              </p>
            </div>
            <Button asChild>
              <Link href="/pagebuilder/content/review">Review it</Link>
            </Button>
          </div>
        )}

        {state.error && <p className="mb-4 text-sm text-destructive">{state.error}</p>}

        <SnapshotList
          snapshots={state.snapshots}
          busy={state.busy}
          hasPending={state.pending !== null}
          onRestore={state.restore}
          onDelete={state.remove}
        />

        <p className="mt-6 text-xs text-muted-foreground">
          Restoring never deletes: a page on the site but absent from the snapshot is left alone.
          Branding and news articles are not part of a snapshot.
        </p>
      </PageShell>
    </AuthenticatedLayout>
  );
}
