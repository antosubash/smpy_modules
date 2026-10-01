import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';

import type { BulkReport } from '../utils/api-records';
import { shortUuid } from '../utils/record-title';
import type { RecordRead } from '../utils/types';

/**
 * What a refused bulk action left the operator to act on.
 *
 * The API is all-or-nothing: a batch one record refuses changes nothing, and
 * the `409` names every record that refused with the status and message that
 * record alone would have answered. A message alone would be useless here —
 * "3 of 12 refused" is not something anybody can fix — so the refusal is a
 * list, and the one button that turns reading it into doing something:
 * "Deselect the ones that failed" leaves the rest ticked, so the retry is one
 * click rather than eleven.
 *
 * Rendered under the toolbar rather than inside the confirm dialog: the list
 * can be as long as the selection, and a dialog is the wrong place to read
 * twenty lines and then act on the page behind it.
 */
export function BulkRefusalReport({
  report,
  records,
  onDeselect,
  onDismiss,
}: {
  report: BulkReport;
  /** U1: the page's own records, so a refused uuid can be named by its
   *  title instead of a raw 32-hex string — `RecordListBulk` already has
   *  them in scope through `selection`'s own source. A refusal naming a
   *  record that has since scrolled off the page (or that belongs to a
   *  related type entirely, as `_lifecycle.py`'s blocker uuids can) falls
   *  back to the uuid, same as before. */
  records: readonly Pick<RecordRead, 'uuid' | 'display_title'>[];
  /** Drops exactly the uuids below from the selection. */
  onDeselect: (uuids: string[]) => void;
  onDismiss: () => void;
}) {
  const { t } = useT();
  const failing = report.failed.map((entry) => entry.uuid);
  const byUuid = new Map(records.map((record) => [record.uuid, record]));
  return (
    <div
      data-testid="records-bulk-refusal"
      className="mb-4 rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm"
      role="alert"
    >
      <p className="font-medium text-destructive">
        {t('records.bulk.refused', {
          count: report.failed.length,
          total: report.requested,
          defaultValue: '{count} of {total} records could not be changed, so nothing was changed.',
        })}
      </p>
      <ul className="mt-2 space-y-1" data-testid="records-bulk-refusal-list">
        {report.failed.map((entry) => {
          const title = byUuid.get(entry.uuid)?.display_title;
          return (
            <li key={entry.uuid} className="break-words">
              <span className="font-medium">{title || entry.uuid}</span>
              {title && (
                <span className="ml-1 text-xs text-muted-foreground" title={entry.uuid}>
                  ({shortUuid(entry.uuid)})
                </span>
              )}
              {' — '}
              {entry.message}
            </li>
          );
        })}
      </ul>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => {
            onDeselect(failing);
            onDismiss();
          }}
        >
          {t('records.bulk.deselect_failing', {
            count: report.failed.length,
            defaultValue: 'Deselect the {count} that failed',
          })}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDismiss}>
          {t('records.bulk.dismiss', { defaultValue: 'Dismiss' })}
        </Button>
      </div>
    </div>
  );
}
