import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { formatBytes } from '../../utils/mediaFormat';
import { downloadUrl, type Snapshot } from '../../utils/snapshotsApi';
import { ConfirmDialog } from '../ConfirmDialog';
import { contentsLine, missingMediaWarning, sourceLabel } from './planSummary';

function taken(snapshot: Snapshot): string {
  if (!snapshot.created_at) return '';
  const when = new Date(snapshot.created_at);
  return Number.isNaN(when.getTime()) ? '' : when.toLocaleString();
}

/**
 * The restore points, newest first.
 *
 * Restore is offered on every row and is deliberately *not* a confirm-heavy
 * action: it only stages a plan for approval, and putting friction here would
 * charge people for looking. The expensive click lives on the review screen.
 */
export function SnapshotList({
  snapshots,
  busy,
  hasPending,
  onRestore,
  onDelete,
}: {
  snapshots: Snapshot[];
  busy: boolean;
  hasPending: boolean;
  onRestore: (snapshot: Snapshot) => Promise<unknown>;
  onDelete: (snapshot: Snapshot) => Promise<unknown>;
}) {
  if (snapshots.length === 0) {
    return (
      <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
        No snapshots yet. Take one before a big change, and this is where you come back to.
      </p>
    );
  }

  return (
    <ul className="divide-y rounded-md border">
      {snapshots.map((snapshot) => {
        const missing = missingMediaWarning(snapshot);
        return (
          <li key={snapshot.id} className="flex flex-wrap items-start justify-between gap-4 p-4">
            <div className="min-w-0 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{snapshot.note || `Snapshot #${snapshot.id}`}</span>
                <Badge variant="secondary">{sourceLabel(snapshot.source)}</Badge>
              </div>
              <p className="text-sm text-muted-foreground">
                {contentsLine(snapshot)} · {formatBytes(snapshot.size_bytes)}
              </p>
              <p className="text-xs text-muted-foreground">
                {taken(snapshot)}
                {snapshot.created_by ? ` · ${snapshot.created_by}` : ''}
              </p>
              {missing && <p className="text-xs text-amber-700">{missing}</p>}
            </div>

            <div className="flex shrink-0 items-center gap-2">
              <Button variant="outline" size="sm" asChild>
                <a href={downloadUrl(snapshot.id)}>Download</a>
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={busy || hasPending}
                title={hasPending ? 'An import is already awaiting approval' : undefined}
                onClick={() => void onRestore(snapshot)}
              >
                Restore…
              </Button>
              <ConfirmDialog
                trigger={
                  <Button variant="ghost" size="sm" disabled={busy}>
                    Delete
                  </Button>
                }
                title="Delete this snapshot?"
                description={
                  <>
                    This restore point goes for good. The site is not affected — but if you were
                    keeping this one to fall back on, download it first.
                  </>
                }
                confirmLabel="Delete snapshot"
                destructive
                level="medium"
                onConfirm={() => onDelete(snapshot)}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
