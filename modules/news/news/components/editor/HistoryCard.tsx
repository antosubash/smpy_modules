import { Button } from '@simple-module-py/ui/components/ui/button';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { listArticleRevisions, type RevisionRead, restoreArticleRevision } from '../../utils/api';
import { ConfirmDialog } from '../ConfirmDialog';

/** Labels for the events the workflow records.
 *
 * `approve` reads as "approved and published" because that is one action: a
 * reviewer who has to approve and then publish separately eventually forgets
 * the second half, so there is no separate `publish` row in the review path and
 * a bare "Approved" would leave a reader of the history wondering.
 */
const EVENTS: Record<RevisionRead['event'], string> = {
  submit: 'Submitted for review',
  approve: 'Approved and published',
  reject: 'Sent back',
  publish: 'Published',
  unpublish: 'Taken down',
};

/** Every transition this article has been through.
 *
 * The rows were being written on every transition and were readable over the
 * API from the day the workflow landed; nothing rendered them, so the audit
 * trail existed and no one could see it.
 *
 * Restoring is behind a confirmation because it overwrites the working draft
 * with an older one — recoverable only by restoring again from a row this very
 * action pushes further down the list.
 */
export function HistoryCard({ articleId }: { articleId: number }) {
  const [revisions, setRevisions] = useState<RevisionRead[] | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    (signal?: AbortSignal) =>
      listArticleRevisions(articleId, signal)
        .then(setRevisions)
        // An empty history and a failed read look the same here on purpose:
        // this is a panel beside the work, not the work.
        .catch(() => setRevisions([])),
    [articleId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const restore = async (revision: RevisionRead) => {
    setBusy(true);
    try {
      await restoreArticleRevision(articleId, revision.id);
      await load();
      toast.success('Draft restored — reopen the body canvas to see it');
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (revisions === null) return null;

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide">History</h2>

      {revisions.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Nothing yet. Submitting, publishing or taking the article down records a row here.
        </p>
      ) : (
        <ol className="space-y-3">
          {revisions.map((revision) => (
            <li key={revision.id} className="border-b pb-3 last:border-0 last:pb-0">
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-sm font-medium">{EVENTS[revision.event] ?? revision.event}</p>
                {revision.created_at && (
                  <time
                    dateTime={revision.created_at}
                    className="shrink-0 text-xs text-muted-foreground"
                  >
                    {new Date(revision.created_at).toLocaleString()}
                  </time>
                )}
              </div>
              {revision.created_by && (
                <p className="text-xs text-muted-foreground">{revision.created_by}</p>
              )}
              {revision.note && <p className="mt-1 text-xs italic">“{revision.note}”</p>}
              <ConfirmDialog
                level="medium"
                title="Restore this version?"
                description="The body you are working on is replaced by the one saved at this point. Anything written since is lost unless it was itself recorded here."
                confirmLabel="Restore"
                onConfirm={() => restore(revision)}
                trigger={
                  <Button variant="ghost" size="sm" className="mt-1 h-7 px-2" disabled={busy}>
                    Restore this version
                  </Button>
                }
              />
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
