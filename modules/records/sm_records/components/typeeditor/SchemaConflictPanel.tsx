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
        <div
          className="space-y-3 rounded-md border border-destructive/50 p-4"
          data-testid="records-schema-report"
        >
          <h2 className="font-medium text-destructive">
            {t('records.type_editor.preview.report_title', {
              defaultValue: 'This change would leave records invalid',
            })}
          </h2>
          <DryRunReportView report={report} />
          <ConfirmDialog
            trigger={
              <Button type="button" variant="destructive">
                {/* U3: `report.failing` counts live and trashed records
                    alike (§8.9's own reasoning — a trashed record still
                    reads back under the schema on restore), while the
                    hub's `invalid_record_count` badge this operator will
                    check afterwards counts live ones only. "(including
                    trashed)" is what keeps the two from reading as a
                    contradiction rather than two honestly different
                    scopes. */}
                {t('records.type_editor.preview.apply_anyway', {
                  count: report.failing,
                  defaultValue:
                    'Apply anyway — {count} record will be marked invalid (including trashed)',
                  defaultValue_other:
                    'Apply anyway — {count} records will be marked invalid (including trashed)',
                })}
              </Button>
            }
            title={t('records.type_editor.preview.apply_anyway_title', {
              defaultValue: 'Apply this change anyway?',
            })}
            description={t('records.type_editor.preview.apply_anyway_description', {
              count: report.failing,
              defaultValue:
                '{count} record will be marked as not satisfying the schema (including trashed), rather than being changed or deleted.',
              defaultValue_other:
                '{count} records will be marked as not satisfying the schema (including trashed), rather than being changed or deleted.',
            })}
            confirmLabel={t('records.type_editor.preview.apply_anyway_confirm', {
              defaultValue: 'Apply anyway',
            })}
            destructive
            onConfirm={onForce}
          />
        </div>
      )}

      {conflicts && (
        <div
          className="space-y-3 rounded-md border border-amber-500/50 bg-amber-500/10 p-4"
          data-testid="records-orphaned-conflicts"
        >
          <h2 className="font-medium">
            {t('records.type_editor.preview.conflicts_title', {
              defaultValue: 'These fields still hold values from a previous delete',
            })}
          </h2>
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
