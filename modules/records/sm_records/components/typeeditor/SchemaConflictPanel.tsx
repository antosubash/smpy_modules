import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';

import type { DryRunReport } from '../../utils/types';
import { ConfirmDialog } from '../ConfirmDialog';
import { DryRunReportView } from './DryRunReportView';
import { OrphanedConflictsList } from './OrphanedConflictsList';

/**
 * The two schema-write 409 shapes that aren't a plain version conflict
 * (design §8.2/§8.8), rendered as real screen state rather than a toast —
 * shared by `TypeEditor`'s save button and `TypeRevisions`' restore, both of
 * which drive it from a `useSchemaApply` instance.
 *
 * `report` — a restrictive change would leave records invalid: "Apply
 * anyway" re-sends with `force: true`, which applies the change and marks
 * the failing records rather than mutating them.
 *
 * `conflicts` — re-adding a key that still holds `_orphaned` values on some
 * records: one decision (`orphaned: 'restore' | 'discard'`) resolves every
 * listed key at once, since that's what the API takes; the list of per-key
 * counts is what the operator is confirming before making it.
 */
export function SchemaConflictPanel({
  report,
  conflicts,
  pending,
  onForce,
  onOrphaned,
}: {
  report: DryRunReport | null;
  conflicts: Record<string, number> | null;
  pending: boolean;
  onForce: () => Promise<unknown>;
  onOrphaned: (choice: 'restore' | 'discard') => Promise<unknown>;
}) {
  const { t } = useT();
  if (!report && !conflicts) return null;

  return (
    <div className="space-y-4">
      {report && (
        <div className="space-y-3 rounded-md border border-destructive/50 p-4">
          <p className="font-medium text-destructive">
            {t('records.type_editor.preview.report_title', {
              defaultValue: 'This change would leave records invalid',
            })}
          </p>
          <DryRunReportView report={report} />
          <ConfirmDialog
            trigger={
              <Button type="button" variant="destructive">
                {t('records.type_editor.preview.apply_anyway', {
                  count: report.failing,
                  defaultValue: 'Apply anyway — {{count}} records will be marked invalid',
                })}
              </Button>
            }
            title={t('records.type_editor.preview.apply_anyway_title', {
              defaultValue: 'Apply this change anyway?',
            })}
            description={t('records.type_editor.preview.apply_anyway_description', {
              count: report.failing,
              defaultValue:
                '{{count}} record(s) will be marked as not satisfying the schema, rather than being changed or deleted.',
            })}
            confirmLabel={t('records.type_editor.preview.apply_anyway_confirm', {
              defaultValue: 'Apply anyway',
            })}
            cancelLabel={t('records.editor.cancel', { defaultValue: 'Cancel' })}
            pendingLabel={t('records.editor.saving', { defaultValue: 'Saving…' })}
            destructive
            onConfirm={onForce}
          />
        </div>
      )}

      {conflicts && (
        <div className="space-y-3 rounded-md border border-amber-500/50 bg-amber-500/10 p-4">
          <p className="font-medium">
            {t('records.type_editor.preview.conflicts_title', {
              defaultValue: 'These fields still hold values from a previous delete',
            })}
          </p>
          <OrphanedConflictsList conflicts={conflicts} />
          <p className="text-sm text-muted-foreground">
            {t('records.type_editor.preview.conflicts_help', {
              defaultValue:
                'Restore brings those values back into the field; discard drops them for good.',
            })}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              disabled={pending}
              onClick={() => {
                void onOrphaned('restore');
              }}
            >
              {t('records.type_editor.preview.orphaned_restore', { defaultValue: 'Restore' })}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => {
                void onOrphaned('discard');
              }}
            >
              {t('records.type_editor.preview.orphaned_discard', { defaultValue: 'Discard' })}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
