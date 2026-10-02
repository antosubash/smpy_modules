import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { keys, useT } from '../../utils/i18n';
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
  pendingSnapshotId,
  onRestore,
  onDelete,
}: {
  snapshots: Snapshot[];
  busy: boolean;
  hasPending: boolean;
  /** The snapshot a staged-but-undecided restore targets, if any. */
  pendingSnapshotId: number | null;
  onRestore: (snapshot: Snapshot) => Promise<unknown>;
  onDelete: (snapshot: Snapshot) => Promise<unknown>;
}) {
  const { t } = useT();
  if (snapshots.length === 0) {
    return (
      <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
        {t(keys.pagebuilder.snapshot_list.empty)}
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
                <span className="font-medium">
                  {snapshot.note || t(keys.pagebuilder.snapshot_list.untitled, { id: snapshot.id })}
                </span>
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
                <a href={downloadUrl(snapshot.id)}>{t(keys.pagebuilder.snapshot_list.download)}</a>
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={busy || hasPending}
                title={hasPending ? t(keys.pagebuilder.snapshot_list.pending_hint) : undefined}
                onClick={() => void onRestore(snapshot)}
              >
                {t(keys.pagebuilder.snapshot_list.restore)}
              </Button>
              <ConfirmDialog
                trigger={
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy || pendingSnapshotId === snapshot.id}
                    title={
                      pendingSnapshotId === snapshot.id
                        ? t(keys.pagebuilder.snapshot_list.staged_hint)
                        : undefined
                    }
                  >
                    {t(keys.pagebuilder.snapshot_list.delete)}
                  </Button>
                }
                title={t(keys.pagebuilder.snapshot_list.delete_title)}
                description={t(keys.pagebuilder.snapshot_list.delete_description)}
                confirmLabel={t(keys.pagebuilder.snapshot_list.delete_confirm)}
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
