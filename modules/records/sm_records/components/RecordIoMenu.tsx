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
  DropdownMenuTrigger,
} from '@simple-module-py/ui/components/ui/dropdown-menu';
import { useRef, useState } from 'react';
import { toast } from 'sonner';

import { exportUrl, type ImportReport, importRecords } from '../utils/io';

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
}: {
  typeKey: string;
  search: string;
  canEdit: boolean;
}) {
  const { t } = useT();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (chosen: File, dryRun: boolean) => {
    setBusy(true);
    try {
      const result = await importRecords(typeKey, chosen, { dryRun });
      setReport(result);
      if (!dryRun && result.failed === 0) {
        toast.success(t('records.io.applied', { defaultValue: 'Import applied' }));
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const onPick = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const chosen = event.target.files?.[0] ?? null;
    // Reset immediately so picking the *same* file twice still fires change.
    event.target.value = '';
    if (!chosen) return;
    setFile(chosen);
    await run(chosen, true);
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="outline" data-testid="records-export-menu">
            {t('records.io.export', { defaultValue: 'Export' })}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem asChild>
            <a href={exportUrl(typeKey, 'json', search)} data-testid="records-export-json">
              {t('records.io.export_json', { defaultValue: 'Download JSON' })}
            </a>
          </DropdownMenuItem>
          <DropdownMenuItem asChild>
            <a href={exportUrl(typeKey, 'csv', search)} data-testid="records-export-csv">
              {t('records.io.export_csv', { defaultValue: 'Download CSV' })}
            </a>
          </DropdownMenuItem>
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
            {t('records.io.import', { defaultValue: 'Import' })}
          </Button>
        </>
      )}

      <Dialog open={report !== null} onOpenChange={(open) => !open && setReport(null)}>
        <DialogContent data-testid="records-import-report">
          <DialogHeader>
            <DialogTitle>
              {report?.dry_run
                ? t('records.io.preview_title', { defaultValue: 'Import preview' })
                : t('records.io.result_title', { defaultValue: 'Import result' })}
            </DialogTitle>
          </DialogHeader>
          {report && <ImportSummary report={report} />}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setReport(null)}>
              {t('records.io.close', { defaultValue: 'Close' })}
            </Button>
            {report?.dry_run && report.failed === 0 && file && (
              <Button
                type="button"
                disabled={busy}
                data-testid="records-import-apply"
                onClick={() => void run(file, false)}
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

/** The counts and the first few row errors. Split out so the menu above reads
 *  as a toolbar rather than as a report renderer. */
function ImportSummary({ report }: { report: ImportReport }) {
  const { t } = useT();
  return (
    <div className="space-y-3 text-sm">
      <p data-testid="records-import-counts">
        {t('records.io.summary', {
          total: report.total,
          created: report.created,
          updated: report.updated,
          skipped: report.skipped,
          failed: report.failed,
          defaultValue:
            '{total} row(s): {created} to create, {updated} to update, {skipped} unchanged, {failed} failed',
        })}
      </p>
      {report.errors.length > 0 && (
        <ul className="max-h-60 space-y-1 overflow-y-auto rounded-lg border p-2">
          {report.errors.map((error) => (
            <li key={`${error.row}-${error.field ?? ''}-${error.message}`}>
              {t('records.io.error_row', {
                row: error.row,
                field: error.field ?? '—',
                message: error.message,
                defaultValue: 'Row {row} ({field}): {message}',
              })}
            </li>
          ))}
        </ul>
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
