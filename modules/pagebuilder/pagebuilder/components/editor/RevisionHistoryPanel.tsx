/** Revision history drawer with per-revision compare and restore. */

import type { PageRevisionRead, RevisionDiff, RevisionEvent } from '../../utils/api';
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
  onRestore: (revisionId: number) => void;
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
    <div className="border-b bg-gray-50 px-4 py-3 text-sm">
      {revisions.length === 0 ? (
        <p className="text-gray-500">No history yet. Publish or submit to record one.</p>
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
                  <span className="text-gray-700 ml-2">{r.title}</span>
                  <span className="text-gray-500 ml-2">
                    {new Date(r.created_at).toLocaleString()}
                  </span>
                  {r.created_by && <span className="text-gray-500 ml-2">by {r.created_by}</span>}
                  {r.note && <div className="text-gray-800 mt-0.5 break-words">Note: {r.note}</div>}
                </div>
                <div className="flex gap-3 shrink-0">
                  {previous && (
                    <button
                      type="button"
                      onClick={() => onCompare(previous.id, r.id)}
                      className="text-blue-600 hover:underline"
                      data-testid={`compare-${r.id}`}
                    >
                      {isOpen ? 'Hide diff' : 'Compare'}
                    </button>
                  )}
                  {RESTORABLE_EVENTS.has(r.event) && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => onRestore(r.id)}
                      className="text-blue-600 hover:underline disabled:opacity-50"
                    >
                      Restore as draft
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {diffError && (
        <p className="mt-2 text-xs text-red-600" data-testid="diff-error">
          {diffError}
        </p>
      )}
      {activeDiff && <DiffSummary diff={activeDiff} />}
    </div>
  );
}
