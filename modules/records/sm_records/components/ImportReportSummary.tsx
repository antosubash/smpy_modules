import { useT } from '@simple-module-py/i18n';

import type { ImportReport, ImportRowError } from '../utils/io';
import type { Translate } from '../utils/translate';
import { EMPTY_CELL } from '../utils/values';

/** A version refusal is worded by `services/_import_rows.py` and always
 *  names the escape hatch by its wire name, since that is the one thing a
 *  file-editing operator cannot see in `RecordIoMenu` otherwise. */
const FORCE_HINT_PATTERN = /force=true/;

/** Whether any row error is the "no version" refusal `force` answers
 *  (`services/_import_rows.py`) — FAIL-1's UI half points the operator at the
 *  one option in `RecordImportOptions` that gets them past it. */
function hasForceableError(errors: ImportRowError[]): boolean {
  return errors.some((error) => FORCE_HINT_PATTERN.test(error.message));
}

/** The preview reads in the future tense ("to create") because it hasn't
 *  happened yet; the result reads in the past tense because it has (UX-10).
 *  Two literal `t()` calls, not one interpolated from a string chosen before
 *  it, for the reason `filterErrorMessage` (`pages/RecordList.tsx`) gives:
 *  `make ci-check-untranslated` reads the call, not a value assembled ahead
 *  of it. */
function summaryText(t: Translate, report: ImportReport): string {
  const vars = {
    total: report.total,
    created: report.created,
    updated: report.updated,
    skipped: report.skipped,
    failed: report.failed,
    // U10: "row(s)" is the only word here that pluralizes, and it counts
    // `total` — every other figure is a sub-count within it, not a second
    // noun of its own.
    count: report.total,
  };
  if (report.dry_run) {
    return t('records.io.summary', {
      ...vars,
      defaultValue:
        '{total} row: {created} to create, {updated} to update, {skipped} unchanged, {failed} failed',
      defaultValue_other:
        '{total} rows: {created} to create, {updated} to update, {skipped} unchanged, {failed} failed',
    });
  }
  return t('records.io.summary_result', {
    ...vars,
    defaultValue:
      '{total} row: {created} created, {updated} updated, {skipped} unchanged, {failed} failed',
    defaultValue_other:
      '{total} rows: {created} created, {updated} updated, {skipped} unchanged, {failed} failed',
  });
}

/** The counts and the first few row errors of one import report — split out
 *  of `RecordIoMenu` so that reads as a toolbar rather than as a report
 *  renderer. */
export function ImportReportSummary({ report }: { report: ImportReport }) {
  const { t } = useT();
  return (
    <div className="space-y-3 text-sm">
      <p data-testid="records-import-counts">{summaryText(t, report)}</p>
      {report.total > 0 && (
        // R21: the report has no per-record titles to show for any bucket —
        // `ImportReport` (`contracts/io.py`) carries counts plus, for a
        // failed row only, its row number and message, never a uuid the
        // list resolved to a display title. Said here rather than left
        // silent, since "first 5 affected titles" is what was asked for.
        // U15: the original wording ("showing titles here would need the
        // import endpoint to return them") explained the team's own backlog
        // to an operator rather than saying what they can actually rely on.
        <p className="text-muted-foreground" data-testid="records-import-titles-note">
          {t('records.io.titles_unavailable', {
            defaultValue: 'Rows are identified by number, not title.',
          })}
        </p>
      )}
      {report.errors.length > 0 && (
        <ul className="max-h-60 space-y-1 overflow-y-auto rounded-lg border p-2">
          {report.errors.map((error) => (
            <li key={`${error.row}-${error.field ?? ''}-${error.message}`}>
              {t('records.io.error_row', {
                row: error.row,
                field: error.field ?? EMPTY_CELL,
                message: error.message,
                defaultValue: 'Row {row} ({field}): {message}',
              })}
            </li>
          ))}
        </ul>
      )}
      {hasForceableError(report.errors) && (
        <p className="text-muted-foreground" data-testid="records-import-force-hint">
          {t('records.io.force_hint', {
            defaultValue:
              'These rows were refused because the file carries no version for a record that already exists — turn on "Overwrite unversioned rows" above and import again.',
          })}
        </p>
      )}
      {report.errors_truncated && (
        <p className="text-muted-foreground">
          {t('records.io.errors_truncated', {
            defaultValue: 'Only the first errors are listed; fix these and try again.',
          })}
        </p>
      )}
    </div>
  );
}
