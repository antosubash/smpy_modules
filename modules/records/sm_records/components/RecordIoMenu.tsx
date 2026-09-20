import { router } from '@inertiajs/react';
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
import { useRef, useState } from 'react';
import { toast } from 'sonner';
import { exportUrl, type ImportReport, importRecords } from '../utils/io';
import type { FieldDef } from '../utils/types';
import { ImportReportSummary } from './ImportReportSummary';
import {
  DEFAULT_IMPORT_OPTIONS,
  type ImportOptionsValue,
  RecordImportOptions,
} from './RecordImportOptions';

// See `pages/RecordList.tsx` for why `t` is typed this loosely here.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

/** The parser's own errors (`services/_io_upload.py`) are accurate but
 *  written for the log, not the person who just picked a file — one names a
 *  query parameter no browser upload can send, the other quotes a JSON
 *  parser's own message. Recognised by a stable substring rather than
 *  rewritten server-side, so this stays a UI concern (UX-5). */
function friendlyImportError(t: Translate, raw: string): string {
  if (raw.includes('cannot tell whether this is JSON or CSV')) {
    return t('records.io.error_unknown_format', {
      defaultValue:
        "Couldn't tell whether that file is JSON or CSV — save it with a .json or .csv extension and try again.",
    });
  }
  if (raw.includes('is not valid JSON')) {
    return t('records.io.error_bad_json', {
      defaultValue:
        "That file isn't valid JSON — open it in a text editor and check it's complete.",
    });
  }
  return raw;
}

type Phase = 'idle' | 'checking' | 'applying';

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
}) {
  const { t } = useT();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [options, setOptions] = useState<ImportOptionsValue>(DEFAULT_IMPORT_OPTIONS);
  const busy = phase !== 'idle';

  const run = async (chosen: File, dryRun: boolean) => {
    setPhase(dryRun ? 'checking' : 'applying');
    try {
      const result = await importRecords(typeKey, chosen, {
        dryRun,
        mode: options.mode,
        onError: options.onError,
        matchBy: options.matchBy,
        force: options.force,
      });
      setReport(result);
      if (!dryRun && result.failed === 0) {
        toast.success(t('records.io.applied', { defaultValue: 'Import applied' }));
      }
      // Reload whenever the apply actually wrote a row, not only on a
      // clean run (M3): `on_error: 'skip'` can write every good row and
      // still report `failed > 0`, and gating on `failed === 0` alone left
      // those writes invisible behind the dialog until a manual page
      // reload. Same partial reload a delete/restore uses
      // (`pages/RecordList.tsx`).
      if (!dryRun && result.created + result.updated > 0) {
        router.reload({ only: ['records'] });
      }
    } catch (error) {
      const raw = error instanceof Error ? error.message : String(error);
      toast.error(friendlyImportError(t, raw));
    } finally {
      setPhase('idle');
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

  const dryRunNow = report ? report.dry_run : phase === 'checking';

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
          <RecordImportOptions
            fields={fields}
            value={options}
            onChange={(patch) => setOptions((prev) => ({ ...prev, ...patch }))}
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

      <Dialog open={report !== null || busy} onOpenChange={(open) => !open && setReport(null)}>
        <DialogContent data-testid="records-import-report">
          <DialogHeader>
            <DialogTitle>
              {dryRunNow
                ? t('records.io.preview_title', { defaultValue: 'Import preview' })
                : t('records.io.result_title', { defaultValue: 'Import result' })}
            </DialogTitle>
          </DialogHeader>
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
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" disabled={busy} onClick={() => setReport(null)}>
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
