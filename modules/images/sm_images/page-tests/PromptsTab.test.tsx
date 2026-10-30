// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PromptsTab } from '../components/prompts/PromptsTab';
import { click, mount, setValue } from './test-dom';
import type { Prompt } from '../utils/types-prompts';
import { flush, stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());

const LIST = '/api/images/collections/c1/prompts';
const GROUPS = '/api/images/collections/c1/groups';
const PRESETS = '/api/images/presets';

function prompt(overrides: Partial<Prompt> = {}): Prompt {
  return {
    id: 'p1',
    collection_id: 'c1',
    name: 'Count',
    scope: 'image',
    instruction: 'Count the trees.',
    output_schema: { type: 'object', properties: { n: { type: 'integer' } }, required: ['n'] },
    inputs: null,
    member_prompt_id: null,
    auto_run: false,
    preset_id: null,
    preset_prompt_id: null,
    revision: 1,
    ...overrides,
  };
}

const SITE = prompt({ id: 'g1', name: 'Site', scope: 'group', inputs: 'images' });
const group = { id: 'grp1', collection_id: 'c1', key: 'site-1', name: null, description: null, image_count: 2, members: [] };
const PRESET = {
  id: 'acme',
  label_key: 'acme.label',
  group_roles: [],
  filename_patterns: [],
  prompts: [],
  has_cross_check: false,
};

afterEach(() => vi.unstubAllGlobals());

const byId = (view: { find: (s: string) => HTMLElement | null }, id: string) =>
  view.find(`[data-testid="${id}"]`);

describe('PromptsTab', () => {
  it('gives an owner or manager the collection-wide runs and the preset picker', async () => {
    const calls = stubFetch({
      [`GET ${LIST}`]: { items: [prompt(), SITE] },
      [`GET ${GROUPS}`]: { items: [group], next_cursor: null },
      [`GET ${PRESETS}`]: { items: [PRESET] },
      'POST /api/images/prompts/p1/run': { status: 'accepted', scope: 'stale', requested: 3 },
      'POST /api/images/collections/c1/apply-preset': { preset_id: 'acme', created: [prompt()] },
    });
    const view = await mount(<PromptsTab collectionId="c1" canEdit canManage />);
    await flush();
    await click(byId(view, 'images-prompt-run-stale-p1'));
    await flush();
    await click(document.querySelector('[data-testid="images-prompt-run-confirm-go"]'));
    expect(calls.at(-1)).toMatchObject({ method: 'POST', body: { scope: 'stale' } });
    await setValue(view.find('#images-preset') as HTMLSelectElement, 'acme');
    await click(byId(view, 'images-preset-apply'));
    await flush();
    const applied = calls.find((c) => c.url.endsWith('/apply-preset'));
    expect(applied?.body).toEqual({ preset_id: 'acme' });
    await view.unmount();
  });

  it('lets an editor run a group prompt on one group, and nothing collection-wide', async () => {
    const calls = stubFetch({
      [`GET ${LIST}`]: { items: [prompt(), SITE] },
      [`GET ${GROUPS}`]: { items: [group], next_cursor: null },
      'POST /api/images/prompts/g1/run': { status: 'accepted', scope: 'stale', requested: 1 },
    });
    const view = await mount(<PromptsTab collectionId="c1" canEdit canManage={false} />);
    await flush();
    expect(byId(view, 'images-prompt-run-all-p1')).toBeNull();
    expect(byId(view, 'images-preset-picker')).toBeNull();
    expect(byId(view, 'images-prompt-group-p1')).toBeNull(); // an image prompt has no group run
    await setValue(byId(view, 'images-prompt-group-g1') as HTMLSelectElement, 'grp1');
    await click(byId(view, 'images-prompt-run-group-g1'));
    expect(calls.at(-1)).toMatchObject({
      url: '/api/images/prompts/g1/run',
      body: { scope: 'stale', group_ids: ['grp1'] },
    });
    // auto-run cannot be switched on by an editor
    await click(byId(view, 'images-prompt-new'));
    expect((byId(view, 'images-prompt-auto-run') as HTMLInputElement).disabled).toBe(true);
    await view.unmount();
  });

  it('shows a viewer the prompts and no way to change or run them', async () => {
    stubFetch({ [`GET ${LIST}`]: { items: [prompt()] } });
    const view = await mount(<PromptsTab collectionId="c1" canEdit={false} canManage={false} />);
    await flush();
    expect(view.host.textContent).toContain('Count');
    for (const id of ['images-prompt-new', 'images-prompt-edit-p1', 'images-prompt-run-missing-p1']) {
      expect(byId(view, id)).toBeNull();
    }
    await view.unmount();
  });

  it('creates a prompt from fields', async () => {
    const calls = stubFetch({
      [`GET ${LIST}`]: { items: [] },
      [`GET ${PRESETS}`]: { items: [] },
      [`POST ${LIST}`]: prompt(),
    });
    const view = await mount(<PromptsTab collectionId="c1" canEdit canManage />);
    await flush();
    await click(byId(view, 'images-prompt-new'));
    await setValue(view.find('#images-prompt-name') as HTMLInputElement, 'Kind');
    await setValue(view.find('#images-prompt-instruction') as HTMLTextAreaElement, 'What is it?');
    await click(byId(view, 'images-schema-add-field'));
    const row = byId(view, 'images-schema-field-0') as HTMLElement;
    await setValue(row.querySelector('input') as HTMLInputElement, 'kind');
    await setValue(row.querySelector('select') as HTMLSelectElement, 'string');
    const choices = row.querySelectorAll('input')[2] as HTMLInputElement;
    await setValue(choices, 'tree, road');
    await click(byId(view, 'images-prompt-submit'));
    await flush();
    const sent = calls.find((c) => c.method === 'POST' && c.url === LIST);
    expect(sent?.body).toEqual({
      name: 'Kind',
      scope: 'image',
      instruction: 'What is it?',
      output_schema: {
        type: 'object',
        properties: { kind: { type: 'string', enum: ['tree', 'road'] } },
      },
      inputs: null,
      member_prompt_id: null,
      auto_run: false,
    });
    await view.unmount();
  });

  it('keeps a schema the fields cannot express, unchanged, as JSON', async () => {
    const rich = { type: 'object', properties: { n: { type: 'integer', minimum: 0 } } };
    const calls = stubFetch({
      [`GET ${LIST}`]: { items: [prompt({ output_schema: rich })] },
      [`GET ${PRESETS}`]: { items: [] },
      'PATCH /api/images/prompts/p1': prompt({ output_schema: rich }),
    });
    const view = await mount(<PromptsTab collectionId="c1" canEdit canManage />);
    await flush();
    await click(byId(view, 'images-prompt-edit-p1'));
    expect(byId(view, 'images-schema-editor')?.dataset.mode).toBe('json');
    expect(byId(view, 'images-schema-advanced')).not.toBeNull();
    expect((byId(view, 'images-schema-mode-fields') as HTMLButtonElement).disabled).toBe(true);
    await click(byId(view, 'images-prompt-submit'));
    await flush();
    const sent = calls.find((c) => c.method === 'PATCH');
    expect((sent?.body as { output_schema: unknown }).output_schema).toEqual(rich);
    expect(sent?.body).not.toHaveProperty('scope');
    await view.unmount();
  });

  it('asks a group prompt over results for its image prompt', async () => {
    stubFetch({ [`GET ${LIST}`]: { items: [prompt()] }, [`GET ${PRESETS}`]: { items: [] } });
    const view = await mount(<PromptsTab collectionId="c1" canEdit canManage />);
    await flush();
    await click(byId(view, 'images-prompt-new'));
    await setValue(view.find('#images-prompt-name') as HTMLInputElement, 'Site');
    await setValue(view.find('#images-prompt-instruction') as HTMLTextAreaElement, 'Sum up.');
    await setValue(view.find('#images-prompt-scope') as HTMLSelectElement, 'group');
    await setValue(view.find('#images-prompt-inputs') as HTMLSelectElement, 'results');
    const submit = byId(view, 'images-prompt-submit') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    await setValue(view.find('#images-prompt-member') as HTMLSelectElement, 'p1');
    expect(submit.disabled).toBe(false);
    expect(byId(view, 'images-prompt-auto-run')).toBeNull();
    await view.unmount();
  });

  it('keeps the list when a reload fails, with an error above it', async () => {
    let reads = 0;
    stubFetch({
      [`GET ${LIST}`]: () => {
        reads += 1;
        if (reads > 1) throw new Error('offline');
        return { items: [prompt()] };
      },
      [`GET ${PRESETS}`]: { items: [PRESET] },
      'POST /api/images/collections/c1/apply-preset': { preset_id: 'acme', created: [] },
    });
    const view = await mount(<PromptsTab collectionId="c1" canEdit canManage />);
    await flush();
    await setValue(view.find('#images-preset') as HTMLSelectElement, 'acme');
    await click(byId(view, 'images-preset-apply'));
    await flush();
    expect(reads).toBe(2);
    expect(byId(view, 'images-prompt-p1')).not.toBeNull(); // the stale list stays
    expect(byId(view, 'images-prompts-error')).not.toBeNull();
    await view.unmount();
  });

  it('replaces the tab with the error only when the first load fails', async () => {
    stubFetch({
      [`GET ${LIST}`]: () => {
        throw new Error('offline');
      },
    });
    const view = await mount(<PromptsTab collectionId="c1" canEdit canManage />);
    await flush();
    expect(byId(view, 'images-prompts')).toBeNull();
    expect(byId(view, 'images-prompts-error')).not.toBeNull();
    await view.unmount();
  });
});
