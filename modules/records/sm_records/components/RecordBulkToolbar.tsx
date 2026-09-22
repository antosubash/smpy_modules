import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';

import type { BulkAction } from '../utils/api-records';
import { bulkActions } from '../utils/bulk-copy';
import { ConfirmDialog } from './ConfirmDialog';

/**
 * The bar above the list once something is ticked: what is selected, and the
 * actions that mean something for the view it is selected in.
 *
 * Which those are, and what each confirmation says, is `utils/bulk-copy` —
 * a rule and a set of sentences, both testable without mounting anything.
 * What is here is the wiring: every action goes through the same destructive
 * `ConfirmDialog` the row actions use, because the whole difference between
 * this and the per-row button is that the operator is about to do it to a
 * number of records they have to recognise first.
 */
export function RecordBulkToolbar({
  count,
  trashed,
  pending,
  onRun,
  onClear,
}: {
  count: number;
  trashed: boolean;
  /** An action is in flight: the bar disables rather than disappears, so the
   *  count stays readable while the request runs. */
  pending?: boolean;
  onRun: (action: BulkAction) => Promise<unknown>;
  onClear: () => void;
}) {
  const { t } = useT();
  if (count === 0) return null;

  return (
    <div
      data-testid="records-bulk-toolbar"
      className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border bg-muted/40 p-2"
    >
      <span className="text-sm font-medium" data-testid="records-bulk-count">
        {t('records.bulk.selected', { count, defaultValue: '{count} selected' })}
      </span>
      {bulkActions(t, { count, trashed }).map((item) => (
        <ConfirmDialog
          key={item.action}
          trigger={
            <Button
              type="button"
              size="sm"
              variant={item.destructive ? 'destructive' : 'outline'}
              disabled={pending}
              data-testid={`records-bulk-${item.action}`}
            >
              {item.label}
            </Button>
          }
          title={item.label}
          description={item.description}
          confirmLabel={item.label}
          cancelLabel={t('records.editor.cancel', { defaultValue: 'Cancel' })}
          pendingLabel={t('records.editor.saving', { defaultValue: 'Saving…' })}
          destructive={item.destructive}
          onConfirm={() => onRun(item.action)}
        />
      ))}
      <Button
        type="button"
        size="sm"
        variant="ghost"
        onClick={onClear}
        data-testid="records-bulk-clear"
      >
        {t('records.bulk.clear', { defaultValue: 'Clear selection' })}
      </Button>
    </div>
  );
}
