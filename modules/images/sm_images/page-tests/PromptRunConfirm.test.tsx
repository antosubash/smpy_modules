// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PromptsTab } from '../components/prompts/PromptsTab';
import { click, mount } from '../test-dom';
import type { Prompt } from '../utils/types-prompts';
import { flush, stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());

const LIST = '/api/images/collections/c1/prompts';
const GROUPS = '/api/images/collections/c1/groups';

const IMAGE: Prompt = {
  id: 'p1',
  collection_id: 'c1',
  name: 'Land cover',
  scope: 'image',
  instruction: 'What land cover?',
  output_schema: null,
  inputs: null,
  member_prompt_id: null,
  auto_run: false,
  preset_id: null,
  preset_prompt_id: null,
  revision: 1,
};
const SITE: Prompt = { ...IMAGE, id: 'g1', name: 'Point summary', scope: 'group', inputs: 'images' };
const group = (id: string) => ({
  id,
  collection_id: 'c1',
  key: id,
  name: null,
  description: null,
  image_count: 5,
  members: [],
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

const q = (id: string) => document.querySelector<HTMLElement>(`[data-testid="${id}"]`);

describe('a collection-wide prompt run asks first (QA TEST-013)', () => {
  it('names how many images it may run on, and runs only once confirmed', async () => {
    const calls = stubFetch({
      [`GET ${LIST}`]: { items: [IMAGE] },
      'GET /api/images/presets': { items: [] },
      'POST /api/images/prompts/p1/run': { status: 'accepted', scope: 'all', requested: 35 },
    });
    const view = await mount(<PromptsTab collectionId="c1" canEdit canManage imageCount={35} />);
    await flush();
    await click(q('images-prompt-run-all-p1'));
    await flush();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    const dialog = q('images-prompt-run-confirm');
    expect(dialog?.textContent).toContain('Run “Land cover”?');
    expect(dialog?.textContent).toContain('up to 35 AI runs, one per image');
    expect(dialog?.textContent).toContain('Every result is replaced');
    await click(q('images-prompt-run-confirm-go'));
    await flush();
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1);
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ scope: 'all' });
    await view.unmount();
  });

  it('cancelling runs nothing', async () => {
    const calls = stubFetch({
      [`GET ${LIST}`]: { items: [IMAGE] },
      'GET /api/images/presets': { items: [] },
    });
    const view = await mount(<PromptsTab collectionId="c1" canEdit canManage imageCount={3} />);
    await flush();
    await click(q('images-prompt-run-missing-p1'));
    await flush();
    expect(q('images-prompt-run-confirm')?.textContent).toContain('Only images or groups without a result');
    await click(q('images-prompt-run-confirm-cancel'));
    await flush();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    await view.unmount();
  });

  it('counts the groups for a group prompt', async () => {
    stubFetch({
      [`GET ${LIST}`]: { items: [SITE] },
      [`GET ${GROUPS}`]: { items: [group('a'), group('b')], next_cursor: null },
      'GET /api/images/presets': { items: [] },
    });
    const view = await mount(<PromptsTab collectionId="c1" canEdit canManage imageCount={10} />);
    await flush();
    await click(q('images-prompt-run-stale-g1'));
    await flush();
    expect(q('images-prompt-run-confirm')?.textContent).toContain('up to 2 AI runs, one per group');
    await view.unmount();
  });
});
