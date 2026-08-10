/** Revision history drawer with per-revision compare and restore. */

import { Button } from '@simple-module-py/ui/components/ui/button';

import type { PageRevisionRead, RevisionDiff, RevisionEvent } from '../../utils/api';
import { ConfirmDialog } from '../ConfirmDialog';
import { DiffSummary } from '../DiffSummary';

const EVENT_LABELS: Record<RevisionEvent, string> = {
  publish: 'Published',
  unpublish: 'Unpublished',
  submit: 'Submitted for review',
  approve: 'Approved',
  reject: 'Rejected',
};

// Revision events whose ``data`` snapshot matches what /p/{slug} served.
const RESTORABLE_EVENTS: ReadonlySet<RevisionEvent> = new Set(['publish', 'approve']);

interface Props {
  revisions: PageRevisionRead[];
  activeDiff: RevisionDiff | null;
  diffError: string | null;
  busy: boolean;
  onCompare: (beforeId: number, afterId: number) => void;
  /** Rejecting surfaces the message inside the confirmation dialog. */
  onRestore: (revisionId: number) => Promise<unknown>;
}

export function RevisionHistoryPanel({
  revisions,
  activeDiff,
  diffError,
  busy,
  onCompare,
  onRestore,
}: Props) {
  return (
    <div className="border-b bg-muted px-4 py-3 text-sm">
      {revisions.length === 0 ? (
        <p className="text-muted-foreground">No history yet. Publish or submit to record one.</p>
      ) : (
        <ul className="space-y-1 max-h-48 overflow-y-auto">
          {revisions.map((r, idx) => {
            // Revisions are sorted newest-first, so the "previous" is
            // the next index. The last item has no predecessor.
            const previous = revisions[idx + 1];
            const isOpen =
              activeDiff !== null &&
              activeDiff.after_id === r.id &&
              previous !== undefined &&
              activeDiff.before_id === previous.id;
            return (
              <li key={r.id} className="flex items-start justify-between gap-3 py-1">
                <div className="flex-1 min-w-0">
                  <span className="font-medium">{EVENT_LABELS[r.event] ?? r.event}</span>
                  <span className="ml-2">{r.title}</span>
                  <span className="ml-2 text-muted-foreground">
                    {new Date(r.created_at).toLocaleString()}
                  </span>
                  {r.created_by && (
                    <span className="ml-2 text-muted-foreground">by {r.created_by}</span>
                  )}
                  {r.note && <div className="mt-0.5 break-words">Note: {r.note}</div>}
                </div>
                <div className="flex gap-3 shrink-0">
                  {previous && (
                    <Button
                      type="button"
                      variant="link"
                      size="sm"
                      className="h-auto p-0"
                      onClick={() => onCompare(previous.id, r.id)}
                      data-testid={`compare-${r.id}`}
                    >
                      {isOpen ? 'Hide diff' : 'Compare'}
                    </Button>
                  )}
                  {RESTORABLE_EVENTS.has(r.event) && (
                    <ConfirmDialog
                      trigger={
                        <Button type="button" variant="link" size="sm" className="h-auto p-0">
                          Restore as draft
                        </Button>
                      }
                      title="Replace the current draft?"
                      description={`Everything unsaved in the editor is overwritten by the "${EVENT_LABELS[r.event] ?? r.event}" revision from ${new Date(r.created_at).toLocaleString()}. The live page is untouched until you publish again.`}
                      confirmLabel="Restore"
                      onConfirm={() => onRestore(r.id)}
                    />
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {diffError && (
        <p className="mt-2 text-xs text-destructive" data-testid="diff-error">
          {diffError}
        </p>
      )}
      {activeDiff && <DiffSummary diff={activeDiff} />}
    </div>
  );
}
