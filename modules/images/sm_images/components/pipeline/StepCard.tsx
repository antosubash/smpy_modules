import { Button } from '@simple-module-py/ui/components/ui/button';
import { Switch } from '@simple-module-py/ui/components/ui/switch';

import { keys, useT } from '../../utils/i18n';
import type { PipelineStep } from '../../utils/types';
import { ParamsForm } from './ParamsForm';

export type StepDraft = { enabled: boolean; params: Record<string, unknown>; removed?: boolean };

/** One step: its toggle, what it needs, and its params form. A step the API
 *  reports as not installed keeps its saved config but cannot be edited; a
 *  manager can only remove it from the config (on the next save), or undo that. */
export function StepCard({
  step,
  draft,
  canEdit,
  counts,
  onChange,
}: {
  step: PipelineStep;
  draft: StepDraft;
  canEdit: boolean;
  counts: Record<string, number>;
  onChange: (next: StepDraft) => void;
}) {
  const { t } = useT();
  const labelId = `images-step-label-${step.id}`;
  const summary = Object.entries(counts)
    .map(([status, n]) => `${status} ${n}`)
    .join(', ');

  return (
    <li className="space-y-3 rounded-md border p-4" data-testid={`images-step-${step.id}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p id={labelId} className="font-medium">
            {step.id}
          </p>
          {step.requires && step.requires.length > 0 && (
            <p className="text-xs text-muted-foreground">
              {t(keys.images.pipeline.requires, { steps: step.requires.join(', ') })}
            </p>
          )}
          {summary && <p className="text-xs text-muted-foreground">{summary}</p>}
        </div>
        <Switch
          aria-labelledby={labelId}
          data-testid={`images-step-toggle-${step.id}`}
          checked={draft.enabled}
          disabled={!canEdit || !step.installed}
          onCheckedChange={(enabled) => onChange({ ...draft, enabled })}
        />
      </div>
      {!step.installed && !draft.removed && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-destructive/40 p-2">
          <p
            className="text-sm text-destructive"
            role="alert"
            data-testid={`images-step-missing-${step.id}`}
          >
            {t(keys.images.pipeline.not_installed)}
          </p>
          {canEdit && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid={`images-step-remove-${step.id}`}
              onClick={() => onChange({ ...draft, removed: true })}
            >
              {t(keys.images.pipeline.remove)}
            </Button>
          )}
        </div>
      )}
      {!step.installed && draft.removed && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-2">
          <p className="text-sm" data-testid={`images-step-removed-${step.id}`}>
            {t(keys.images.pipeline.removed)}
          </p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            data-testid={`images-step-undo-${step.id}`}
            onClick={() => onChange({ ...draft, removed: false })}
          >
            {t(keys.images.pipeline.undo)}
          </Button>
        </div>
      )}
      {step.installed && step.params_schema && (
        <ParamsForm
          stepId={step.id}
          schema={step.params_schema}
          value={draft.params}
          disabled={!canEdit || !draft.enabled}
          onChange={(params) => onChange({ ...draft, params })}
        />
      )}
    </li>
  );
}
