import { Button } from '@simple-module-py/ui/components/ui/button';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { hasActiveRuns, usePipelinePoll } from '../../hooks/usePipelinePoll';
import { getPipeline, restartPipeline, savePipeline } from '../../utils/api';
import { errorText } from '../../utils/api-net';
import { keys, useT } from '../../utils/i18n';
import type { PipelineOverview, RestartScope } from '../../utils/types';
import { StepCard, type StepDraft } from './StepCard';

type Drafts = Record<string, StepDraft>;

/** How long the counts are watched after each restart request returns: a
 *  broker-queued restart answers before it resets a run. */
export const RESTART_WATCH_MS = 60_000;

function draftsOf(overview: PipelineOverview): Drafts {
  return Object.fromEntries(
    overview.steps.map((s) => [s.id, { enabled: s.enabled, params: { ...(s.params ?? {}) } }]),
  );
}

/** The `PUT` body: every enabled step, plus any disabled step already in the
 *  saved config; a step that is not installed is sent back exactly as saved,
 *  unless the owner removed it. */
export function payloadOf(overview: PipelineOverview, drafts: Drafts) {
  const saved = overview.config.steps ?? {};
  const out: Record<string, Record<string, unknown>> = Object.create(null);
  for (const step of overview.steps) {
    if (!step.installed) {
      if (step.id in saved && !drafts[step.id]?.removed) out[step.id] = saved[step.id];
      continue;
    }
    const draft = drafts[step.id];
    if (draft.enabled || step.id in saved)
      out[step.id] = { ...draft.params, enabled: draft.enabled };
  }
  return out;
}

/**
 * A collection's pipeline: each step's toggle and params, the stale banner and
 * the restart actions. Saving only stores the config - the server plans newly
 * enabled steps on the next dispatch or restart - so a successful save offers
 * a restart for the existing images. While runs are pending or running (or a
 * restart request is outstanding - an eager host runs it inline) the counts
 * are read again every few seconds; a draft being edited is kept. After a
 * restart request returns they are watched for {@link RESTART_WATCH_MS} more
 * (each request renews it), whatever the counts say meanwhile.
 */
export function PipelineTab({
  collectionId,
  canManage,
}: {
  collectionId: string;
  canManage: boolean;
}) {
  const { t } = useT();
  const [overview, setOverview] = useState<PipelineOverview | null>(null);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [dirty, setDirty] = useState(false);
  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;
  // Bumped around every write of ours: a poll read begun before it is stale.
  const epoch = useRef(0);
  const [saving, setSaving] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const busy = saving || restarting;
  // The latest restart request's watch: its own identity and deadline.
  const [watch, setWatch] = useState<{ until: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [offerRestart, setOfferRestart] = useState(false);

  const load = useCallback(async () => {
    try {
      const next = await getPipeline(collectionId);
      setOverview(next);
      setDrafts(draftsOf(next));
      setDirty(false);
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  }, [collectionId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (watch === null) return;
    const timer = setTimeout(
      () => setWatch((w) => (w === watch ? null : w)),
      Math.max(0, watch.until - Date.now()),
    );
    return () => clearTimeout(timer);
  }, [watch]);

  const polling = restarting || watch !== null || hasActiveRuns(overview);
  usePipelinePoll(
    collectionId,
    polling,
    (next) => {
      setOverview(next);
      if (!dirtyRef.current) setDrafts(draftsOf(next));
    },
    epoch,
  );

  const save = async () => {
    if (!overview) return;
    setSaving(true);
    epoch.current += 1;
    try {
      const next = await savePipeline(collectionId, payloadOf(overview, drafts));
      epoch.current += 1;
      setOverview(next);
      setDrafts(draftsOf(next));
      setDirty(false);
      setError(null);
      setOfferRestart(true);
      toast(t(keys.images.pipeline.saved));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSaving(false);
    }
  };

  const restart = async (scope: RestartScope) => {
    setRestarting(true);
    epoch.current += 1;
    try {
      await restartPipeline(collectionId, scope);
      epoch.current += 1;
      setWatch({ until: Date.now() + RESTART_WATCH_MS }); // a fresh object per request
      setOfferRestart(false);
      toast(t(keys.images.pipeline.restarted));
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setRestarting(false);
    }
  };

  if (!overview) {
    return (
      <p className="text-sm text-muted-foreground" role={error ? 'alert' : undefined}>
        {error ?? t(keys.images.common.loading)}
      </p>
    );
  }

  const restartButtons = (scopes: RestartScope[]) =>
    scopes.map((scope) => (
      <Button
        key={scope}
        type="button"
        variant="outline"
        disabled={busy}
        data-testid={`images-pipeline-restart-${scope}`}
        onClick={() => void restart(scope)}
      >
        {t(keys.images.pipeline.restart[scope])}
      </Button>
    ));

  return (
    <section className="space-y-4" aria-labelledby="images-pipeline-title">
      <h2 id="images-pipeline-title" className="text-lg font-semibold">
        {t(keys.images.pipeline.title)}
      </h2>
      {error && (
        <p className="text-sm text-destructive" role="alert" data-testid="images-pipeline-error">
          {error}
        </p>
      )}
      {overview.stale > 0 && (
        <p className="rounded-md border p-3 text-sm" data-testid="images-pipeline-stale">
          {t(keys.images.pipeline.stale, { count: overview.stale })}
        </p>
      )}
      {overview.not_installed > 0 && (
        <p
          className="rounded-md border border-destructive/40 p-3 text-sm text-destructive"
          data-testid="images-pipeline-not-installed"
        >
          {t(keys.images.pipeline.results_not_installed, { count: overview.not_installed })}
        </p>
      )}
      {offerRestart && canManage && (
        <div className="space-y-2 rounded-md border p-3" data-testid="images-pipeline-offer">
          <p className="text-sm">{t(keys.images.pipeline.offer)}</p>
          <div className="flex flex-wrap gap-2">
            {restartButtons(['stale', 'all'])}
            <Button type="button" variant="ghost" onClick={() => setOfferRestart(false)}>
              {t(keys.images.pipeline.later)}
            </Button>
          </div>
        </div>
      )}
      <ul className="space-y-3">
        {overview.steps.map((step) => (
          <StepCard
            key={step.id}
            step={step}
            draft={drafts[step.id]}
            canEdit={canManage}
            counts={overview.status[step.id] ?? {}}
            onChange={(next) => {
              setDrafts((d) => ({ ...d, [step.id]: next }));
              setDirty(true);
            }}
          />
        ))}
      </ul>
      {canManage && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            disabled={busy || !dirty}
            data-testid="images-pipeline-save"
            onClick={() => void save()}
          >
            {saving ? t(keys.images.common.saving) : t(keys.images.pipeline.save)}
          </Button>
          {restartButtons(['failed', 'stale', 'all'])}
        </div>
      )}
    </section>
  );
}
