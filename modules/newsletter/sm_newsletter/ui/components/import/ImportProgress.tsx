/** A queued, running or finished import: `processed / total`, a bar and the five counts. */

import { Progress } from '@simple-module-py/ui/components/ui/progress';

import { keys, useT } from '../../utils/i18n';
import type { ImportJob, ImportStatus } from '../../utils/importTypes';

const copy = keys.newsletter.import;

export const STATUS_LABELS: Record<ImportStatus, string> = {
  staged: copy.status.staged,
  queued: copy.status.queued,
  running: copy.status.running,
  done: copy.status.done,
  failed: copy.status.failed,
};

const COUNTS = [
  ['created', copy.counts.created],
  ['updated', copy.counts.updated],
  ['skipped', copy.counts.skipped],
  ['suppressed', copy.counts.suppressed],
  ['failed', copy.counts.failed],
] as const;

export function ImportCounts({ job }: { job: ImportJob }) {
  const { t } = useT();
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      {COUNTS.map(([field, label]) => (
        <div key={field} className="rounded-md border p-3">
          <dt className="text-xs text-muted-foreground">{t(label)}</dt>
          <dd className="text-lg font-semibold">{job[field]}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ImportProgress({ job }: { job: ImportJob }) {
  const { t } = useT();
  const percent = job.total > 0 ? Math.min(100, Math.round((job.processed / job.total) * 100)) : 0;
  return (
    <div className="grid gap-3">
      <p role="status" className="text-sm font-medium">
        {t(STATUS_LABELS[job.status])}:{' '}
        {t(copy.progress, { processed: job.processed, total: job.total })}
      </p>
      <Progress
        value={percent}
        aria-label={t(copy.progress, { processed: job.processed, total: job.total })}
      />
      <ImportCounts job={job} />
    </div>
  );
}
