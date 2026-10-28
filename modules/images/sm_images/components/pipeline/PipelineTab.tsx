import { Button } from '@simple-module-py/ui/components/ui/button';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { getPipeline, restartPipeline, savePipeline } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import type { PipelineOverview, RestartScope } from '../../utils/types';
import { StepCard, type StepDraft } from './StepCard';

type Drafts = Record<string, StepDraft>;

function draftsOf(overview: PipelineOverview): Drafts {
  return Object.fromEntries(
    overview.steps.map((s) => [s.id, { enabled: s.enabled, params: { ...(s.params ?? {}) } }]),
  );
}

/** The `PUT` body: every enabled step, plus any disabled step already in the
 *  saved config; a step that is not installed is sent back exactly as saved. */
export function payloadOf(overview: PipelineOverview, drafts: Drafts) {
  const saved = overview.config.steps ?? {};
  const out: Record<string, Record<string, unknown>> = {};
  for (const step of overview.steps) {
    if (!step.installed) {
      if (step.id in saved) out[step.id] = saved[step.id];
      continue;
    }
    const draft = drafts[step.id];
    if (draft.enabled || step.id in saved)
      out[step.id] = { ...draft.params, enabled: draft.enabled };
  }
  return out;
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/**
 * A collection's pipeline: each step's toggle and params, the stale banner and
 * the restart actions. Saving only stores the config - the server plans newly
 * enabled steps on the next dispatch or restart - so a successful save offers
 * a restart for the existing images.
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
  const [busy, setBusy] = useState(false);
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
      setError(message(e));
    }
  }, [collectionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!overview) return;
    setBusy(true);
    try {
      const next = await savePipeline(collectionId, payloadOf(overview, drafts));
      setOverview(next);
      setDrafts(draftsOf(next));
      setDirty(false);
      setError(null);
      setOfferRestart(true);
      toast(t(keys.images.pipeline.saved));
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  };

  const restart = async (scope: RestartScope) => {
    setBusy(true);
    try {
      await restartPipeline(collectionId, scope);
      setOfferRestart(false);
      toast(t(keys.images.pipeline.restarted));
      await load();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
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
            {busy ? t(keys.images.common.saving) : t(keys.images.pipeline.save)}
          </Button>
          {restartButtons(['failed', 'stale', 'all'])}
        </div>
      )}
    </section>
  );
}
