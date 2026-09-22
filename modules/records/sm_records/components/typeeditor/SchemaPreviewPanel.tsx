import { Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useEffect, useRef, useState } from 'react';

import { ApiError, getPreviewJob, previewSchema } from '../../utils/api';
import type { SchemaPreview, TypeRead } from '../../utils/types';
import { DryRunReportView } from './DryRunReportView';
import { stripUids } from './formHelpers';
import { SchemaChangeList } from './SchemaChangeList';
import type { EditableField } from './types';

/** How often a deferred preview is polled. One second: the scan reports its
 *  progress per batch of `reindex_batch_size`, so anything faster polls for
 *  a number that has not moved. */
const POLL_MS = 1000;

type Progress = { checked: number; total: number } | null;

/** Which schema the report on screen was produced for: the draft being
 *  edited ("Preview changes") or the one already saved ("Check records"). */
type Mode = 'draft' | 'saved';

/**
 * "Preview changes": `POST .../schema/preview` writes nothing (design
 * §8.9) — it classifies the proposed `fields` and dry-runs it, so this
 * button is safe to press as often as the draft changes.
 *
 * The result is treated as stale the moment `fields` moves to a new
 * reference — tracked by holding on to the exact `fields` a preview was
 * fetched for and comparing rather than clearing it from an effect — so a
 * fresh keystroke after "Preview changes" can't leave a report on screen
 * that no longer matches the draft.
 *
 * Above `preview_sync_limit` records the endpoint answers `202` with a job id
 * instead of the report (F10): the same request, the same button, and the
 * only visible difference is that "Checking…" becomes "Checked N of M…" while
 * the scan runs. `job` is held in state and polled by the effect below rather
 * than awaited in `runPreview`, so unmounting the panel stops the polling
 * instead of leaving a promise writing to a component that is gone.
 */
export function SchemaPreviewPanel({
  typeKey,
  saved,
  fields,
  displayField,
  slugField,
  dirty,
}: {
  typeKey: string;
  /** The type as the server last returned it. "Check records" (UX review
   *  R7b) previews *this* rather than the draft: the same endpoint, the
   *  schema exactly as saved, with `rescan: true` — which is what makes the
   *  answer real. A no-change preview is not restrictive, so without the flag
   *  `_dry_run.py::needs_dry_run` skips the scan and answers `failing: 0`
   *  without reading a record; with it the server scans against the stored
   *  schema and names the records that no longer fit, which is the worklist a
   *  forced apply leaves behind. */
  saved: TypeRead;
  fields: EditableField[];
  /** The editor's current `display_field`/`slug_field` form values (empty
   *  string = cleared) — sent alongside `fields` on every preview so a
   *  pointer-only edit (no field added/removed/changed) doesn't preview as
   *  "No changes" (F5). */
  displayField: string;
  slugField: string;
  dirty: boolean;
}) {
  const { t } = useT();
  const [preview, setPreview] = useState<SchemaPreview | null>(null);
  const [previewedFields, setPreviewedFields] = useState<EditableField[] | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [expired, setExpired] = useState(false);
  const [progress, setProgress] = useState<Progress>(null);
  // The exact `fields` array `runPreview` was called with — snapshotted once,
  // at request time, and read back only by the deferred (job) branch below.
  // Unlike a ref reassigned every render, this can't drift to whatever the
  // admin has typed by the time a long-running preview job lands (M1): both
  // the sync and deferred paths then mark `previewedFields` against the
  // draft that was actually sent, not the latest one.
  const requestedFieldsRef = useRef<EditableField[]>(fields);
  const [mode, setMode] = useState<Mode>('draft');

  // A saved-schema check is never stale: the draft moving underneath it
  // doesn't change which records fail the schema that is actually applied.
  const stale = preview !== null && mode === 'draft' && previewedFields !== fields;

  const runPreview = async (which: Mode = 'draft') => {
    requestedFieldsRef.current = fields;
    setMode(which);
    setPending(true);
    setError(null);
    setProgress(null);
    setJob(null);
    setFailed(false);
    setExpired(false);
    try {
      const result = await previewSchema(
        typeKey,
        which === 'draft'
          ? {
              fields: stripUids(fields),
              display_field: displayField || null,
              slug_field: slugField || null,
            }
          : {
              fields: saved.fields,
              display_field: saved.display_field,
              slug_field: saved.slug_field,
              // The saved schema is its own diff, so there is nothing for the
              // server to classify as restrictive and it would skip the scan.
              // This is the question "which records does the schema refuse
              // now", which only a forced scan answers.
              rescan: true,
            },
      );
      if ('job' in result) {
        // Deferred: stay `pending` — the effect below owns the rest.
        setJob(result.job);
        return;
      }
      setPreview(result);
      setPreviewedFields(fields);
      setPending(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPending(false);
    }
  };

  useEffect(() => {
    if (job === null) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const state = await getPreviewJob(typeKey, job);
        if (cancelled) return;
        setProgress({ checked: state.checked, total: state.total });
        if (state.status === 'running') return;
        setJob(null);
        setPending(false);
        if (state.preview) {
          setPreview(state.preview);
          setPreviewedFields(requestedFieldsRef.current);
        } else {
          setFailed(true);
        }
      } catch (err) {
        if (cancelled) return;
        setJob(null);
        setPending(false);
        // The registry is in-process (`services/preview_jobs.py`): a 404
        // means a worker restart, a multi-worker host, or the TTL pruned it
        // — not a real failure, so this gets its own copy rather than the
        // server's "no schema preview job '…' for '…'" sentence (UX-4).
        if (err instanceof ApiError && err.status === 404) {
          setExpired(true);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    };
    void tick();
    const timer = setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [job, typeKey]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          disabled={!dirty || pending}
          data-testid="records-preview-changes"
          onClick={() => void runPreview('draft')}
        >
          {!pending
            ? t('records.type_editor.preview.button', { defaultValue: 'Preview changes' })
            : progress
              ? t('records.type_editor.preview.progress', {
                  checked: progress.checked,
                  total: progress.total,
                  defaultValue: 'Checked {checked} of {total}…',
                })
              : t('records.type_editor.preview.checking', { defaultValue: 'Checking…' })}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={pending}
          data-testid="records-check-records"
          onClick={() => void runPreview('saved')}
        >
          {t('records.type_editor.preview.check_button', { defaultValue: 'Check records' })}
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        {t('records.type_editor.preview.check_help', {
          defaultValue:
            '"Check records" runs the same dry run against the schema exactly as it is saved, and marks the records that fail so the list can show them. "Preview changes" writes nothing.',
        })}
      </p>
      {(error || failed) && !expired && (
        <p className="text-sm text-destructive" role="alert">
          {error ??
            t('records.type_editor.preview.failed', {
              defaultValue: 'The check could not be completed. Try previewing again.',
            })}
        </p>
      )}
      {expired && (
        <p className="text-sm text-destructive" role="alert" data-testid="records-preview-expired">
          {t('records.type_editor.preview.expired', {
            defaultValue: 'The preview expired; preview again.',
          })}{' '}
          <Button
            type="button"
            variant="link"
            className="h-auto p-0 text-sm"
            data-testid="records-preview-expired-retry"
            onClick={() => void runPreview(mode)}
          >
            {t('records.type_editor.preview.retry', { defaultValue: 'Preview again' })}
          </Button>
        </p>
      )}
      {preview && !stale && (
        <div className="space-y-3 rounded-md border p-4" data-testid="records-schema-preview">
          {mode === 'draft' ? (
            <SchemaChangeList preview={preview} />
          ) : (
            <p className="text-sm font-medium" data-testid="records-check-records-title">
              {t('records.type_editor.preview.check_title', {
                defaultValue: 'Records checked against the saved schema',
              })}
            </p>
          )}
          {/* A preview of the saved schema is a preview of no change, and the
              server skips the scan for one — which is why "Check records"
              sends `rescan: true` above. The report below is therefore a real
              scan of the stored schema, and is rendered as one. */}
          <DryRunReportView report={preview.report} />
          {/* The report names at most `DRY_RUN_SAMPLE` records; the scan just
              marked *every* one it found, so this is where the rest of the
              worklist is. Only after a saved-schema check: a draft preview
              marked nothing, and the link would list whatever an earlier
              check left behind under a report about something else. */}
          {mode === 'saved' && preview.report.failing > 0 && (
            <Link
              href={`/admin/records/${typeKey}?filter=invalid:eq:true`}
              className="inline-block text-sm text-primary hover:underline"
              data-testid="records-check-records-link"
            >
              {t('records.type_editor.preview.check_worklist', {
                count: preview.report.failing,
                defaultValue: 'Show the {count} marked record',
                defaultValue_other: 'Show the {count} marked records',
              })}
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
