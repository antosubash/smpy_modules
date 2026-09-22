import { router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { useRef, useState } from 'react';
import { toast } from 'sonner';

import { DEFAULT_IMPORT_OPTIONS, type ImportOptionsValue } from '../components/RecordImportOptions';
import {
  formatImportLimit,
  friendlyImportError,
  type ImportReport,
  importFileTooLarge,
  importRecords,
} from '../utils/io';

export type ImportPhase = 'idle' | 'checking' | 'applying';

/**
 * `RecordIoMenu`'s import state: the picked file, the options, the report,
 * and the one request that is allowed to answer.
 *
 * Extracted from the component for R10, which is two defects in one place:
 *
 * 1. The options handler ran `run(file, true, next)` *inside* the
 *    `setOptions` updater. Updaters must be pure — React re-invokes them
 *    under StrictMode and may under concurrent rendering, and this one POSTs
 *    a file. Computing the next value and starting the run are two
 *    statements here.
 * 2. Overlapping dry runs had no sequencing. Change two options quickly and
 *    whichever response lands last wins, while the first one's `finally`
 *    clears `phase` to `'idle'` mid-flight — a spinner that stops while a
 *    request is still running, over a report that may be the older one.
 *    Every run takes a ticket from `runId`; a response that is not the
 *    current ticket is dropped, `phase` included.
 *
 * Also the one place a file's size is checked before it is uploaded
 * (R9/M13).
 */
export function useRecordImport(typeKey: string, maxImportBytes: number) {
  const { t } = useT();
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [phase, setPhase] = useState<ImportPhase>('idle');
  const [options, setOptions] = useState<ImportOptionsValue>(DEFAULT_IMPORT_OPTIONS);
  /** The run whose answer is still wanted. Incremented per request; a
   *  response carrying an older ticket is a stale one. */
  const runId = useRef(0);

  /** `overrideOptions` lets a change made *while the dialog is already open*
   *  (the options trigger lives inside it, above Apply — R21) re-run the dry
   *  run against the new choice immediately, instead of against the
   *  closed-over `options` state from before the click that changed it. */
  const run = async (chosen: File, dryRun: boolean, overrideOptions?: ImportOptionsValue) => {
    const opts = overrideOptions ?? options;
    const ticket = runId.current + 1;
    runId.current = ticket;
    setPhase(dryRun ? 'checking' : 'applying');
    try {
      const result = await importRecords(typeKey, chosen, {
        dryRun,
        mode: opts.mode,
        onError: opts.onError,
        matchBy: opts.matchBy,
        force: opts.force,
      });
      if (ticket !== runId.current) return;
      setReport(result);
      // R26: the dialog switches to "Import result" for this same outcome —
      // announcing it a second time with a toast was the duplicate the
      // review filed. The dialog stays open and names the reload below.
      // Reload whenever the apply actually wrote a row, not only on a clean
      // run (M3): `on_error: 'skip'` can write every good row and still
      // report `failed > 0`, and gating on `failed === 0` alone left those
      // writes invisible behind the dialog until a manual page reload. Same
      // partial reload a delete/restore uses (`pages/RecordList.tsx`).
      if (!dryRun && result.created + result.updated > 0) {
        router.reload({ only: ['records'] });
      }
    } catch (error) {
      if (ticket !== runId.current) return;
      const raw = error instanceof Error ? error.message : String(error);
      toast.error(friendlyImportError(t, raw));
    } finally {
      if (ticket === runId.current) setPhase('idle');
    }
  };

  /** A freshly picked file: refused here if it is over the limit, otherwise
   *  dry-run straight away. Answers whether it was accepted. */
  const pick = async (chosen: File): Promise<boolean> => {
    if (importFileTooLarge(chosen.size, maxImportBytes)) {
      // Said here, before the upload: the server's own refusal is a 413 that
      // arrives only after the whole file has gone up the wire (R9/M13).
      toast.error(
        t('records.io.too_large', {
          name: chosen.name,
          limit: formatImportLimit(maxImportBytes),
          defaultValue: '"{name}" is larger than the {limit} import limit.',
        }),
      );
      return false;
    }
    setFile(chosen);
    await run(chosen, true);
    return true;
  };

  const changeOptions = (patch: Partial<ImportOptionsValue>) => {
    const next = { ...options, ...patch };
    setOptions(next);
    if (file) void run(file, true, next);
  };

  return {
    file,
    report,
    phase,
    options,
    busy: phase !== 'idle',
    limitText: formatImportLimit(maxImportBytes),
    pick,
    changeOptions,
    apply: () => (file ? run(file, false) : Promise.resolve()),
    close: () => setReport(null),
  };
}
