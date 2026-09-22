import { useT } from '@simple-module-py/i18n';

import { useBulkActions } from '../hooks/useBulkActions';
import type { RecordSelection } from '../hooks/useRecordSelection';
import { BulkRefusalReport } from './BulkRefusalReport';
import { EmptyTrashButton } from './EmptyTrashButton';
import { RecordBulkToolbar } from './RecordBulkToolbar';

/**
 * Everything the record list grows once an editor can act on more than one
 * record: the selection toolbar, "Empty trash", the refusal panel and the
 * live region that says what happened.
 *
 * One component rather than four in the page, for the 300-line cap and
 * because they are one feature — the toolbar's outcome is what the panel and
 * the live region report, and all three read the same hook.
 *
 * Rendered only for a caller holding `records.edit`; the table is given no
 * tick boxes at all in the other case, so there is never a selection this has
 * to explain it cannot act on. Rendered for *every* such caller though, rows
 * or no rows: the toolbar and "Empty trash" hide themselves when there is
 * nothing to act on, and the live region has to outlive the reload that
 * empties the list — otherwise the one action that leaves no rows behind is
 * the one that announces nothing.
 */
export function RecordListBulk({
  typeKey,
  trashed,
  selection,
  filters,
  total,
  capped = false,
}: {
  typeKey: string;
  trashed: boolean;
  selection: RecordSelection;
  /** Every `filter=` term the list is showing — empty when none is in force,
   *  and empty when the URL's was refused, because "empty what this screen
   *  shows" has to mean the query the screen actually ran. */
  filters: readonly string[];
  /** The listing's `total`: what "Empty trash" is about, and the number the
   *  operator types to confirm it. */
  total: number;
  capped?: boolean;
}) {
  const { t } = useT();
  const bulk = useBulkActions(typeKey, t, {
    uuids: selection.uuids,
    filters,
    onDone: selection.clear,
  });

  return (
    <>
      {trashed && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <EmptyTrashButton
            count={total}
            typeKey={typeKey}
            filtered={filters.length > 0}
            capped={capped}
            onEmpty={bulk.empty}
          />
        </div>
      )}
      <RecordBulkToolbar
        count={selection.count}
        trashed={trashed}
        pending={bulk.pending}
        onRun={bulk.run}
        onClear={selection.clear}
      />
      {bulk.report && (
        <BulkRefusalReport
          report={bulk.report}
          onDeselect={selection.deselect}
          onDismiss={bulk.dismissReport}
        />
      )}
      {/* The list swaps its rows through a partial reload with no focus move,
          so a bulk action that worked is otherwise silent to a screen reader
          — the toast is visual and the rows simply change. */}
      <p className="sr-only" role="status" aria-live="polite" data-testid="records-bulk-status">
        {bulk.announcement}
      </p>
    </>
  );
}
