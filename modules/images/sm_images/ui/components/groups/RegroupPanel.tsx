import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useState } from 'react';

import { useRegroupJob } from '../../hooks/useRegroupJob';
import { cancelRegroup, regroup } from '../../utils/api-groups';
import { errorText } from '../../utils/api-net';
import { keys, useT } from '../../utils/i18n';
import { errorCodeLabel } from '../../utils/labels';
import type { RegroupResult } from '../../utils/types';

/** Group the collection's images by a filename pattern. "Preview" counts what
 *  would change and writes nothing; "Apply" does it (and is safe to repeat). A
 *  big collection answers with a background job, whose progress is shown here. */
export function RegroupPanel({
  collectionId,
  onApplied,
  onClose,
}: {
  collectionId: string;
  onApplied: () => void;
  onClose: () => void;
}) {
  const { t } = useT();
  const text = keys.images.groups.regroup;
  const progress = text.progress;
  const [pattern, setPattern] = useState('');
  const [reassign, setReassign] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RegroupResult | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const { job, gone, error: pollError } = useRegroupJob(jobId, onApplied);

  const run = async (dryRun: boolean) => {
    setBusy(true);
    setError(null);
    setResult(null);
    setJobId(null);
    try {
      const done = await regroup(collectionId, { pattern, reassign, dry_run: dryRun });
      if ('job_id' in done) {
        setJobId(done.job_id);
      } else {
        setResult(done);
        if (!dryRun) onApplied();
      }
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    if (!job) return;
    try {
      await cancelRegroup(job.id);
    } catch (e) {
      setError(errorText(e));
    }
  };

  const running = job?.status === 'running' && !gone && !pollError;

  return (
    <div className="space-y-3 rounded-md border p-4" data-testid="images-regroup">
      <h3 className="font-medium">{t(text.title)}</h3>
      <p className="text-xs text-muted-foreground">{t(text.help)}</p>
      <div className="grid gap-2">
        <Label htmlFor="images-regroup-pattern">{t(text.pattern)}</Label>
        <Input
          id="images-regroup-pattern"
          value={pattern}
          maxLength={500}
          className="font-mono"
          onChange={(e) => {
            setPattern(e.target.value);
            setResult(null);
          }}
        />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={reassign}
          data-testid="images-regroup-reassign"
          onChange={(e) => {
            setReassign(e.target.checked);
            setResult(null);
          }}
        />
        {t(text.reassign)}
      </label>
      {error && (
        <p className="text-sm text-destructive" role="alert" data-testid="images-regroup-error">
          {error}
        </p>
      )}
      {result && (
        <p className="text-sm" role="status" data-testid="images-regroup-result">
          {t(text.result, { ...result })}
        </p>
      )}
      {(gone || pollError) && (
        <p className="text-sm text-destructive" role="alert" data-testid="images-regroup-lost">
          {gone ? t(progress.gone) : t(progress.lost, { reason: pollError ?? '' })}
        </p>
      )}
      {job && (
        <div className="space-y-2" role="status" data-testid="images-regroup-job">
          <p className="text-sm" data-testid="images-regroup-progress">
            {t(progress[job.status], {
              ...job,
              reason: job.error_code ? errorCodeLabel(t, job.error_code) : '',
            })}
          </p>
          {job.dry_run && job.status === 'completed' && (
            <p className="text-xs text-muted-foreground">{t(progress.preview_note)}</p>
          )}
          {running && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="images-regroup-cancel"
              onClick={() => void stop()}
            >
              {t(progress.cancel)}
            </Button>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          disabled={busy || running || !pattern.trim()}
          data-testid="images-regroup-preview"
          onClick={() => void run(true)}
        >
          {t(text.preview)}
        </Button>
        <Button
          type="button"
          disabled={busy || running || !pattern.trim()}
          data-testid="images-regroup-apply"
          onClick={() => void run(false)}
        >
          {t(text.apply)}
        </Button>
        <Button type="button" variant="ghost" onClick={onClose}>
          {t(text.close)}
        </Button>
      </div>
    </div>
  );
}
