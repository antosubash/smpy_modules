import { Button } from '@simple-module-py/ui/components/ui/button';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { listArticleRevisions, type RevisionRead, restoreArticleRevision } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import { ConfirmDialog } from '../ConfirmDialog';

/** Labels for the events the workflow records.
 *
 * `approve` reads as "approved and published" because that is one action: a
 * reviewer who has to approve and then publish separately eventually forgets
 * the second half, so there is no separate `publish` row in the review path and
 * a bare "Approved" would leave a reader of the history wondering.
 */
const EVENTS: Record<RevisionRead['event'], string> = {
  submit: keys.news.history.event_submit,
  approve: keys.news.history.event_approve,
  reject: keys.news.history.event_reject,
  publish: keys.news.history.event_publish,
  unpublish: keys.news.history.event_unpublish,
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
  const { t } = useT();
  const copy = keys.news.history;
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
      toast.success(t(copy.restored_toast));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (revisions === null) return null;

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <h2 className="text-sm font-semibold uppercase tracking-wide">{t(copy.heading)}</h2>

      {revisions.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t(copy.empty)}</p>
      ) : (
        <ol className="space-y-3">
          {revisions.map((revision) => (
            <li key={revision.id} className="border-b pb-3 last:border-0 last:pb-0">
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-sm font-medium">
                  {EVENTS[revision.event] ? t(EVENTS[revision.event]) : revision.event}
                </p>
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
                title={t(copy.restore_title)}
                description={t(copy.restore_description)}
                confirmLabel={t(copy.restore_confirm)}
                onConfirm={() => restore(revision)}
                trigger={
                  <Button variant="ghost" size="sm" className="mt-1 h-7 px-2" disabled={busy}>
                    {t(copy.restore_trigger)}
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
