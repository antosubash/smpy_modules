import { useT } from '@simple-module-py/i18n';

import type { DryRunReport } from '../../utils/types';
import { OrphanedConflictsList } from './OrphanedConflictsList';

/**
 * The dry-run report `POST .../schema/preview` returns, and the same shape a
 * `409` on `PUT`/`.../restore` carries inline (design §8.9) — one renderer
 * for both, since a restrictive change's report reads identically whether it
 * came from a deliberate preview or from a save that got refused.
 */
export function DryRunReportView({ report }: { report: DryRunReport }) {
  const { t } = useT();
  return (
    <div className="space-y-2 text-sm">
      <p>
        {t('records.type_editor.preview.report_summary', {
          checked: report.checked,
          failing: report.failing,
          defaultValue: '{checked} records checked, {failing} would fail',
        })}
      </p>
      {report.sample.length > 0 && (
        <ul className="space-y-1.5">
          {report.sample.map((rec) => (
            <li key={rec.uuid}>
              {/* A type without a `display_field` sends `display_title: ""`
                  (design §8.9) — fall back to the uuid's first 8 characters
                  rather than a blank bullet. */}
              <span className="font-medium">{rec.display_title || rec.uuid.slice(0, 8)}</span>
              <ul className="ml-4 list-inside list-disc text-muted-foreground">
                {rec.errors.map((e) => (
                  <li key={`${rec.uuid}:${e.field}`}>
                    {e.field}: {e.message}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
      <OrphanedConflictsList conflicts={report.orphaned_conflicts} />
    </div>
  );
}
