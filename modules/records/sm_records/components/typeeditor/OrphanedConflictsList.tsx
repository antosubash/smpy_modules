import { useT } from '@simple-module-py/i18n';

/**
 * "{{key}}: {{count}} records still hold a removed value" — shared by
 * `DryRunReportView` (a report's own `orphaned_conflicts`) and
 * `SchemaConflictPanel` (the top-level `conflicts` a 409 sends when
 * re-adding an orphaned key, design §8.8), so the two render identically.
 */
export function OrphanedConflictsList({ conflicts }: { conflicts: Record<string, number> }) {
  const { t } = useT();
  const entries = Object.entries(conflicts);
  if (entries.length === 0) return null;
  return (
    <ul className="space-y-1 text-sm">
      {entries.map(([key, count]) => (
        <li key={key}>
          {t('records.type_editor.preview.orphaned_conflict', {
            key,
            count,
            defaultValue: '{{key}}: {{count}} records still hold a removed value',
          })}
        </li>
      ))}
    </ul>
  );
}
