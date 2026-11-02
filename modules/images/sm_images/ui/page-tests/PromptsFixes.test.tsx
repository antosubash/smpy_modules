// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PromptsTab } from '../components/prompts/PromptsTab';
import type { Prompt } from '../utils/types-prompts';
import { collection, flush, image, stubFetch } from './support';
import { click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());

const Collection = (await import('../../pages/Collection')).default;

const LIST = '/api/images/collections/c1/prompts';

function prompt(overrides: Partial<Prompt> = {}): Prompt {
  return {
    id: 'p1',
    collection_id: 'c1',
    name: 'Count',
    scope: 'image',
    instruction: 'Count the trees.',
    output_schema: { type: 'object', properties: { n: { type: 'integer' } } },
    inputs: null,
    member_prompt_id: null,
    auto_run: false,
    preset_id: null,
    preset_prompt_id: null,
    revision: 1,
    ...overrides,
  };
}

afterEach(() => vi.unstubAllGlobals());

const byId = (view: { find: (s: string) => HTMLElement | null }, id: string) =>
  view.find(`[data-testid="${id}"]`);

async function openNew() {
  const calls = stubFetch({
    [`GET ${LIST}`]: { items: [] },
    'GET /api/images/presets': { items: [] },
    [`POST ${LIST}`]: prompt(),
  });
  const view = await mount(<PromptsTab collectionId="c1" canEdit canManage />);
  await flush();
  await click(byId(view, 'images-prompt-new'));
  await setValue(view.find('#images-prompt-name') as HTMLInputElement, 'Kind');
  await setValue(view.find('#images-prompt-instruction') as HTMLTextAreaElement, 'What?');
  return { view, calls };
}

const output = (view: { find: (s: string) => Element | null }) =>
  view.find('#images-prompt-output') as HTMLSelectElement;

describe('prompt form fixes', () => {
  it('keeps the schema draft, even invalid JSON, across a switch to free text and back', async () => {
    const { view } = await openNew();
    await click(byId(view, 'images-schema-mode-json'));
    await setValue(byId(view, 'images-schema-json') as HTMLTextAreaElement, '{"type": ');
    await setValue(output(view), 'text');
    await setValue(output(view), 'structured');
    expect((byId(view, 'images-schema-json') as HTMLTextAreaElement).value).toBe('{"type": ');
    expect((byId(view, 'images-prompt-submit') as HTMLButtonElement).disabled).toBe(true);
    await view.unmount();
  });

  it('sends the edited fields after a switch to free text and back', async () => {
    const { view, calls } = await openNew();
    await click(byId(view, 'images-schema-add-field'));
    const row = byId(view, 'images-schema-field-0') as HTMLElement;
    await setValue(row.querySelector('input') as HTMLInputElement, 'kind');
    await setValue(output(view), 'text');
    await setValue(output(view), 'structured');
    expect(
      (byId(view, 'images-schema-field-0')?.querySelector('input') as HTMLInputElement | null)
        ?.value,
    ).toBe('kind');
    await click(byId(view, 'images-prompt-submit'));
    await flush();
    const sent = calls.find((c) => c.method === 'POST');
    expect((sent?.body as { output_schema: unknown } | undefined)?.output_schema).toEqual({
      type: 'object',
      properties: { kind: { type: 'string' } },
    });
    await view.unmount();
  });

  it('refuses a field named like an object prototype key', async () => {
    const { view } = await openNew();
    await click(byId(view, 'images-schema-add-field'));
    const row = byId(view, 'images-schema-field-0') as HTMLElement;
    await setValue(row.querySelector('input') as HTMLInputElement, '__proto__');
    expect(byId(view, 'images-schema-field-error-0')).not.toBeNull();
    expect((byId(view, 'images-prompt-submit') as HTMLButtonElement).disabled).toBe(true);
    await view.unmount();
  });
});

describe('group results', () => {
  it('shows a failed run’s stored output as the previous result, not as current', async () => {
    stubFetch({
      [`GET ${LIST}`]: {
        items: [prompt({ id: 'g1', name: 'Site', scope: 'group', inputs: 'images' })],
      },
      'GET /api/images/presets': { items: [] },
      'GET /api/images/collections/c1/groups': { items: [], next_cursor: null },
      'GET /api/images/prompts/g1/results': {
        items: [
          {
            id: 1,
            prompt_id: 'g1',
            image_id: null,
            group_id: 'grp1',
            status: 'failed',
            result_text: null,
            result_data: { verdict: 'old' },
            error: 'quota_exceeded',
            cross_check: null,
            stale: false,
            review_status: 'unreviewed',
          },
        ],
        next_cursor: null,
      },
    });
    const view = await mount(<PromptsTab collectionId="c1" canEdit canManage />);
    await flush();
    await click(byId(view, 'images-prompt-results-g1'));
    await flush();
    const row = byId(view, 'images-group-result-1') as HTMLElement;
    expect(row.dataset.status).toBe('failed');
    expect(byId(view, 'images-group-result-previous-1')?.textContent).toContain('old');
    expect(byId(view, 'images-group-result-current-1')).toBeNull();
    expect(row.textContent).toContain('quota');
    await view.unmount();
  });
});

describe('run a prompt on chosen images', () => {
  const rights = {
    can_edit: true,
    can_manage: false,
    can_share: false,
    can_publish: false,
    direct_upload_threshold: 1024,
  };

  it('lets an editor pick images and run an image prompt where missing or stale', async () => {
    const calls = stubFetch({
      'GET /api/images/collections/c1/images': {
        items: [image('i1'), image('i2'), image('i3')],
        next_cursor: null,
        total: 3,
      },
      [`GET ${LIST}`]: { items: [prompt(), prompt({ id: 'g1', scope: 'group', name: 'Site' })] },
      'POST /api/images/prompts/p1/run': { status: 'accepted', scope: 'stale', requested: 2 },
    });
    const view = await mount(<Collection collection={collection()} {...rights} />);
    await flush();
    await click(byId(view, 'images-gallery-select'));
    await click(view.find('[data-testid="images-gallery-pick-i1"]'));
    await click(view.find('[data-testid="images-gallery-pick-i3"]'));
    await click(byId(view, 'images-run-on-images'));
    await flush();
    const which = byId(view, 'images-run-on-images-prompt') as HTMLSelectElement;
    expect(Array.from(which.options).map((o) => o.value)).toEqual(['', 'p1']); // image prompts only
    const scope = byId(view, 'images-run-on-images-scope') as HTMLSelectElement;
    expect(Array.from(scope.options).map((o) => o.value)).toEqual(['missing', 'stale']);
    await setValue(which, 'p1');
    await setValue(scope, 'stale');
    await click(byId(view, 'images-run-on-images-go'));
    await flush();
    expect(calls.at(-1)).toMatchObject({
      url: '/api/images/prompts/p1/run',
      body: { scope: 'stale', image_ids: ['i1', 'i3'] },
    });
    await view.unmount();
  });

  it('offers no selection to a viewer', async () => {
    stubFetch({
      'GET /api/images/collections/c1/images': {
        items: [image('i1')],
        next_cursor: null,
        total: 1,
      },
    });
    const view = await mount(<Collection collection={collection()} {...rights} can_edit={false} />);
    await flush();
    expect(byId(view, 'images-gallery-select')).toBeNull();
    await view.unmount();
  });
});
