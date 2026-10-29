/** `/api/images` prompt and preset endpoints. */

import { send } from './api';
import type { Preset, Prompt, PromptFields, PromptRun, PromptRunScope } from './types-prompts';

const BASE = '/api/images';

const jsonBody = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
  headers: { 'Content-Type': 'application/json' },
});

export async function listPrompts(collectionId: string): Promise<Prompt[]> {
  const { items } = await send<{ items: Prompt[] }>(`${BASE}/collections/${collectionId}/prompts`);
  return items;
}

export function createPrompt(collectionId: string, body: PromptFields): Promise<Prompt> {
  return send(`${BASE}/collections/${collectionId}/prompts`, jsonBody('POST', body));
}

/** Only the fields sent change; `scope` is fixed at creation, so it is dropped. */
export function updatePrompt(id: string, body: Partial<PromptFields>): Promise<Prompt> {
  const { scope: _fixed, ...changes } = body;
  return send(`${BASE}/prompts/${id}`, jsonBody('PATCH', changes));
}

export function deletePrompt(id: string): Promise<void> {
  return send(`${BASE}/prompts/${id}`, { method: 'DELETE' });
}

/** The whole collection (owner or manager), or named groups of a group prompt
 *  (`groupIds`; with `missing`/`stale` an editor may too). */
export function runPrompt(
  id: string,
  scope: PromptRunScope,
  groupIds?: string[],
): Promise<PromptRun> {
  const body = groupIds ? { scope, group_ids: groupIds } : { scope };
  return send(`${BASE}/prompts/${id}/run`, jsonBody('POST', body));
}

export async function listPresets(): Promise<Preset[]> {
  const { items } = await send<{ items: Preset[] }>(`${BASE}/presets`);
  return items;
}

export function applyPreset(
  collectionId: string,
  presetId: string,
): Promise<{ preset_id: string; created: Prompt[] }> {
  return send(
    `${BASE}/collections/${collectionId}/apply-preset`,
    jsonBody('POST', { preset_id: presetId }),
  );
}
