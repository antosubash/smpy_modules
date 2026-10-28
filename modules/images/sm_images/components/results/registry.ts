import type { ComponentType } from 'react';

import type { StepRun } from '../../utils/types';

export type ResultKind = 'step' | 'prompt_result' | 'cross_check';

/** What a result view is rendered with. `output` is `null` for someone who may
 *  view but not edit the collection: the server withholds it. */
export type ResultViewProps = {
  kind: ResultKind;
  id: string;
  output: Record<string, unknown> | null;
  run: StepRun | null;
};

export type ResultViewRegistration = {
  kind: ResultKind;
  /** The step id (`kind: 'step'`), the prompt id or the cross-check id. */
  id: string;
  component: ComponentType<ResultViewProps>;
};

const views = new Map<string, ComponentType<ResultViewProps>>();

const slot = (kind: ResultKind, id: string) => `${kind}:${id}`;

/**
 * Register the component that renders one kind of result. A plugin calls this
 * from its `images-steps.ts`, which `sm_images/images-steps.ts` globs in. A
 * second registration for the same `(kind, id)` throws: two plugins fighting
 * over one view would otherwise be settled by import order.
 */
export function registerResultView(view: ResultViewRegistration): void {
  const key = slot(view.kind, view.id);
  if (views.has(key)) throw new Error(`A result view for ${key} is already registered`);
  views.set(key, view.component);
}

export function getResultView(
  kind: ResultKind,
  id: string,
): ComponentType<ResultViewProps> | undefined {
  return views.get(slot(kind, id));
}

/** For tests. */
export function clearResultViews(): void {
  views.clear();
}
