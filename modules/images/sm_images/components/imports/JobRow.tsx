import { Button } from '@simple-module-py/ui/components/ui/button';
import { toast } from 'sonner';

import { isActive, isStalled } from '../../hooks/useImportJobs';
import { errorText } from '../../utils/api-net';
import { keys, useT } from '../../utils/i18n';
import { errorCodeLabel, importKindLabel, jobStatusLabel } from '../../utils/labels';
import type { ImportControl, ImportJob } from '../../utils/types';
import { ConfirmDialog } from '../ConfirmDialog';
import { ImportFailures, isRowError } from './ImportFailures';

export { FAILURES_SHOWN } from './ImportFailures';

/** The controls the API permits for a job in this state. */
export function allowedControls(job: ImportJob, stalled: boolean): ImportControl[] {
  if (job.status === 'uploading' || job.status === 'resetting') return [];
  if (stalled || job.status === 'paused') {
    return job.status === 'paused' ? ['resume', 'restart'] : ['resume'];
  }
  if (isActive(job)) return job.status === 'running' ? ['pause'] : [];
  const out: ImportControl[] = ['restart'];
  if (job.failed_count > 0) out.push('retry-failed');
  return out;
}

const CONTROL_LABEL = {
  pause: keys.images.imports.job.pause,
  resume: keys.images.imports.job.resume,
  restart: keys.images.imports.job.restart,
  'retry-failed': keys.images.imports.job.retry_failed,
} satisfies Record<ImportControl, string>;

export function JobRow({
  job,
  canEdit,
  onControl,
  onRemove,
}: {
  job: ImportJob;
  canEdit: boolean;
  onControl: (job: ImportJob, control: ImportControl) => Promise<void>;
  onRemove: (job: ImportJob) => Promise<void>;
}) {
  const { t, locale } = useT();
  const text = keys.images.imports.job;
  const stalled = isStalled(job);
  const processed = job.done_count + job.duplicate_count + job.failed_count;
  const known = job.total_count > 0;
  const jobErrors = job.errors.filter((e) => !isRowError(e));
  const percent = known ? Math.min(100, Math.round((processed / job.total_count) * 100)) : null;

  const run = async (control: ImportControl) => {
    try {
      await onControl(job, control);
    } catch (e) {
      toast.error(t(text.control_failed, { reason: errorText(e) }));
    }
  };

  return (
    <li
      className="space-y-2 rounded-md border p-3"
      data-testid="images-import-job"
      data-status={job.status}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{importKindLabel(t, job.kind)}</span>
        <span
          className={`rounded px-2 py-0.5 text-xs ${job.status === 'failed' || stalled ? 'bg-destructive/10 text-destructive' : 'bg-muted'}`}
          data-testid="images-import-status"
        >
          {jobStatusLabel(t, job.status, stalled)}
        </span>
        <span className="text-xs text-muted-foreground">
          {t(text.started, { when: new Date(job.created_at).toLocaleString(locale) })}
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent ?? undefined}
        className="h-2 overflow-hidden rounded bg-muted"
      >
        <div
          className={`h-full bg-primary ${percent === null && isActive(job) ? 'w-1/3 animate-pulse' : ''}`}
          style={percent === null ? undefined : { width: `${percent}%` }}
        />
      </div>
      <p className="text-sm text-muted-foreground" data-testid="images-import-progress">
        {known
          ? t(text.progress, { done: processed, total: job.total_count })
          : t(text.progress_unknown, { done: processed })}
        {' · '}
        {t(text.counts, {
          added: job.done_count,
          duplicates: job.duplicate_count,
          failed: job.failed_count,
        })}
      </p>
      {jobErrors.length > 0 && (job.status === 'failed' || stalled || job.failed_count > 0) && (
        <ul className="text-sm text-destructive" data-testid="images-import-errors">
          {jobErrors.map((e, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: a job's error log is append-only
            <li key={`${e.code}-${i}`} title={e.code}>
              {errorCodeLabel(t, e.code)}
            </li>
          ))}
        </ul>
      )}
      <ImportFailures errors={job.errors} failed={job.failed_count} />
      {canEdit && (
        <div className="flex flex-wrap gap-2">
          {allowedControls(job, stalled).map((control) => (
            <Button
              key={control}
              type="button"
              size="sm"
              variant="outline"
              data-testid={`images-import-${control}`}
              onClick={() => void run(control)}
            >
              {t(CONTROL_LABEL[control])}
            </Button>
          ))}
          <ConfirmDialog
            trigger={
              <Button type="button" size="sm" variant="outline" data-testid="images-import-delete">
                {t(text.delete)}
              </Button>
            }
            title={t(text.delete_title)}
            description={t(text.delete_body)}
            confirmLabel={t(text.delete_confirm)}
            onConfirm={() => onRemove(job)}
          />
        </div>
      )}
    </li>
  );
}
