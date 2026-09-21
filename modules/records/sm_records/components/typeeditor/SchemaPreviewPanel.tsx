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
   *  schema exactly as saved. Note what the server then does — a no-change
   *  preview is not restrictive, so `_dry_run.py::needs_dry_run` skips the
   *  scan and answers `failing: 0` without reading a record. The panel says
   *  so rather than dressing that up as a clean bill of health; re-deriving
   *  the worklist of a forced apply needs a rescan the API does not offer
   *  yet (or R7c's stored flag). */
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
            '"Check records" runs the same dry run against the schema exactly as it is saved. Neither button writes anything.',
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
          {/* A preview of the saved schema is, by construction, a preview of
              no change — and `services/_dry_run.py::needs_dry_run` skips the
              scan for one, answering `checked: N, failing: 0` without having
              looked at a record. Rendering that as a dry-run result would say
              "0 would fail" about records that are marked invalid, which is
              the opposite of what R7b is for; so the no-change answer gets
              its own sentence instead. Re-deriving the worklist needs the
              server to accept a rescan (or R7c's stored flag). */}
          {mode === 'saved' && preview.changes.length === 0 ? (
            <p className="text-sm text-muted-foreground" data-testid="records-check-not-rescanned">
              {t('records.type_editor.preview.check_skipped', {
                count: preview.report.checked,
                defaultValue:
                  'Nothing has changed since this schema was saved, so the server did not re-scan these {count} records — it runs the check only for a change that could break something.',
              })}
            </p>
          ) : (
            <DryRunReportView report={preview.report} />
          )}
        </div>
      )}
    </div>
  );
}
