import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@simple-module-py/ui/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@simple-module-py/ui/components/ui/dropdown-menu';
import { Spinner } from '@simple-module-py/ui/components/ui/spinner';
import { ChevronDownIcon } from 'lucide-react';
import { useRef } from 'react';
import { useRecordImport } from '../hooks/useRecordImport';
import {
  DEFAULT_MAX_IMPORT_BYTES,
  exportScopeLabel,
  exportUrl,
  importApplyBlockedReason,
  importOptionsSummary,
} from '../utils/io';
import type { FieldDef } from '../utils/types';
import { ImportReportSummary } from './ImportReportSummary';
import { RecordImportOptions } from './RecordImportOptions';

/** Export (JSON / CSV) and Import for the record-list toolbar.
 *
 *  The import is **always dry-run first**: the file is posted, the server
 *  reports what it would do, and only then is there a button that writes. The
 *  endpoint defaults to a dry run too (`services/import_.py`), so this is the
 *  UI agreeing with the API rather than the only thing standing between a
 *  mis-picked file and every record of a type.
 */
export function RecordIoMenu({
  typeKey,
  search,
  canEdit,
  fields,
  trashed = false,
  filtered = false,
  recordCount = 0,
  maxImportBytes = DEFAULT_MAX_IMPORT_BYTES,
}: {
  typeKey: string;
  search: string;
  canEdit: boolean;
  /** The type's fields — `RecordImportOptions` offers each `unique` one as a
   *  `match_by` choice alongside `uuid`/`slug`. */
  fields: FieldDef[];
  /** The list is showing the trash: the export menu says so next to the
   *  links, since that file cannot be re-imported (UX-11). */
  trashed?: boolean;
  /** A `?filter=` is in force (U16) — export honours it the same way the
   *  list does, so the menu says "filtered" rather than implying a full
   *  export. */
  filtered?: boolean;
  /** `records.total` under the list's current filter/trashed state (U16) —
   *  what the download actually contains, said before the click rather
   *  than discovered after. */
  recordCount?: number;
  /** `RecordsSettings.max_import_bytes`, as `views.py::record_list` sends
   *  it. A file over it is refused here (R9/M13) instead of being uploaded
   *  in full to be answered with a 413. */
  maxImportBytes?: number;
}) {
  const { t } = useT();
  const input = useRef<HTMLInputElement>(null);
  const { file, report, phase, options, busy, limitText, pick, changeOptions, apply, close } =
    useRecordImport(typeKey, maxImportBytes);

  const onPick = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const chosen = event.target.files?.[0] ?? null;
    // Reset immediately so picking the *same* file twice still fires change.
    event.target.value = '';
    if (chosen) await pick(chosen);
  };

  const dryRunNow = report ? report.dry_run : phase === 'checking';
  // Options only matter before a write happens — once `report` is a real
  // result (`dry_run: false`), the run they described already happened.
  const canAdjustOptions = canEdit && file !== null && dryRunNow;
  const blockedReason = report ? importApplyBlockedReason(t, report, options.onError) : null;
  const scope = exportScopeLabel(t, { trashed, filtered, count: recordCount });

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="outline" data-testid="records-export-menu">
            {t('records.io.export', { defaultValue: 'Export' })}
            <ChevronDownIcon className="size-4 opacity-60" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem asChild>
            <a href={exportUrl(typeKey, 'json', search)} data-testid="records-export-json">
              {t('records.io.export_json_scoped', {
                scope,
                defaultValue: 'Download JSON ({scope})',
              })}
            </a>
          </DropdownMenuItem>
          <DropdownMenuItem asChild>
            <a href={exportUrl(typeKey, 'csv', search)} data-testid="records-export-csv">
              {t('records.io.export_csv_scoped', {
                scope,
                defaultValue: 'Download CSV ({scope})',
              })}
            </a>
          </DropdownMenuItem>
          {trashed && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuLabel
                className="max-w-64 text-wrap font-normal text-muted-foreground"
                data-testid="records-export-trash-note"
              >
                {t('records.io.trash_export_note', {
                  defaultValue:
                    "A trash export can't be re-imported — restore or purge the records first.",
                })}
              </DropdownMenuLabel>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {canEdit && (
        <>
          <input
            ref={input}
            type="file"
            accept=".json,.csv,application/json,text/csv"
            className="hidden"
            data-testid="records-import-input"
            onChange={onPick}
          />
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            data-testid="records-import-button"
            onClick={() => input.current?.click()}
          >
            {phase === 'checking' ? (
              <span className="inline-flex items-center gap-1.5">
                <Spinner className="size-3.5" />
                {t('records.io.checking_button', { defaultValue: 'Checking…' })}
              </span>
            ) : (
              t('records.io.import', { defaultValue: 'Import' })
            )}
          </Button>
        </>
      )}

      <Dialog open={report !== null || busy} onOpenChange={(open) => !open && close()}>
        <DialogContent data-testid="records-import-report">
          <DialogHeader>
            <DialogTitle>
              {dryRunNow
                ? t('records.io.preview_title', { defaultValue: 'Import preview' })
                : t('records.io.result_title', { defaultValue: 'Import result' })}
            </DialogTitle>
          </DialogHeader>
          {file && (
            // R21: names the file and restates the rules it was just
            // checked against — both used to be invisible by this point,
            // the file because nothing echoed it and the options because
            // the popover that set them had already closed.
            <p className="text-sm text-muted-foreground" data-testid="records-import-file-summary">
              {file.name}
              {' — '}
              {importOptionsSummary(t, options, fields)}
              <br />
              {t('records.io.limit_note', {
                limit: limitText,
                defaultValue: 'Files up to {limit}.',
              })}
            </p>
          )}
          {busy && (
            <div
              className="flex items-center gap-2 text-sm text-muted-foreground"
              data-testid="records-import-progress"
            >
              <Spinner className="size-4" />
              {phase === 'checking'
                ? t('records.io.checking', { defaultValue: 'Checking the file…' })
                : t('records.io.applying', { defaultValue: 'Writing the import…' })}
            </div>
          )}
          {report && <ImportReportSummary report={report} />}
          {blockedReason && (
            <p
              id="records-import-blocked"
              className="text-sm text-destructive"
              role="alert"
              data-testid="records-import-blocked"
            >
              {blockedReason}
            </p>
          )}
          {canAdjustOptions && (
            <div>
              <RecordImportOptions
                fields={fields}
                value={options}
                onChange={changeOptions}
                disabled={busy}
              />
            </div>
          )}
          <div className="flex justify-end gap-2">
            {/* U15: the dialog's own X control (framework-owned) has the
                fixed accessible name "Close" — naming this button the same
                thing gave the dialog two controls with one name. */}
            <Button type="button" variant="outline" disabled={busy} onClick={close}>
              {t('records.io.close', { defaultValue: 'Done' })}
            </Button>
            {report?.dry_run && file && (
              <Button
                type="button"
                disabled={busy || blockedReason !== null}
                aria-describedby={blockedReason ? 'records-import-blocked' : undefined}
                data-testid="records-import-apply"
                onClick={() => void apply()}
              >
                {t('records.io.apply', { defaultValue: 'Apply import' })}
              </Button>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
