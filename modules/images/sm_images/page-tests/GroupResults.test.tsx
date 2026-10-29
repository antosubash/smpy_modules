// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PromptsTab } from '../components/prompts/PromptsTab';
import { act, click, mount, setValue } from '../test-dom';
import type { Prompt } from '../utils/types-prompts';
import { stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());

const SITE: Prompt = {
  id: 'g1',
  collection_id: 'c1',
  name: 'Site',
  scope: 'group',
  instruction: 'Sum up.',
  output_schema: null,
  inputs: 'images',
  member_prompt_id: null,
  auto_run: false,
  preset_id: null,
  preset_prompt_id: null,
  revision: 1,
};
const RESULTS = 'GET /api/images/prompts/g1/results';

function result(id: number, status: string, data: Record<string, unknown> | null) {
  return {
    id,
    prompt_id: 'g1',
    image_id: null,
    group_id: `grp${id}`,
    status,
    result_text: null,
    result_data: data,
    error: status === 'failed' ? 'ai_error' : null,
    cross_check: null,
    stale: false,
    review_status: 'unreviewed',
  };
}

const base = {
  'GET /api/images/collections/c1/prompts': { items: [SITE] },
  'GET /api/images/presets': { items: [] },
  'GET /api/images/collections/c1/groups': {
    items: [{ id: 'grp1', collection_id: 'c1', key: 'site-1', name: null, description: null, image_count: 1, members: [] }],
    next_cursor: null,
  },
};

const settle = () => act(async () => vi.advanceTimersByTimeAsync(0));
const byId = (view: { find: (s: string) => HTMLElement | null }, id: string) =>
  view.find(`[data-testid="${id}"]`);

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function open(routes: Record<string, unknown>) {
  vi.useFakeTimers();
  const calls = stubFetch({ ...base, ...routes });
  const view = await mount(<PromptsTab collectionId="c1" canEdit canManage />);
  await settle();
  await click(byId(view, 'images-prompt-results-g1'));
  await settle();
  return { view, calls };
}

describe('group results panel', () => {
  it('reads the results again after a run, so a failed re-run is not shown as the old success', async () => {
    let reads = 0;
    const { view } = await open({
      [RESULTS]: () => ({
        items: [++reads === 1 ? result(1, 'completed', { verdict: 'old' }) : result(1, 'failed', { verdict: 'old' })],
        next_cursor: null,
      }),
      'POST /api/images/prompts/g1/run': { status: 'accepted', scope: 'stale', requested: 1 },
    });
    expect(byId(view, 'images-group-result-current-1')).not.toBeNull();
    await setValue(byId(view, 'images-prompt-group-g1') as HTMLSelectElement, 'grp1');
    await click(byId(view, 'images-prompt-run-group-g1'));
    await settle();
    expect(byId(view, 'images-group-result-1')?.dataset.status).toBe('failed');
    expect(byId(view, 'images-group-result-current-1')).toBeNull();
    expect(byId(view, 'images-group-result-previous-1')).not.toBeNull();
    await view.unmount();
  });

  it('polls while a run is in flight, then stops', async () => {
    let reads = 0;
    const { view, calls } = await open({
      [RESULTS]: () => ({
        items: [++reads < 3 ? result(1, 'running', null) : result(1, 'completed', { verdict: 'new' })],
        next_cursor: null,
      }),
    });
    expect(byId(view, 'images-group-result-1')?.dataset.status).toBe('running');
    await act(async () => vi.advanceTimersByTimeAsync(3100));
    await act(async () => vi.advanceTimersByTimeAsync(3100));
    expect(byId(view, 'images-group-result-current-1')?.textContent).toContain('new');
    const seen = calls.filter((c) => c.url.includes('/prompts/g1/results')).length;
    await act(async () => vi.advanceTimersByTimeAsync(10000));
    expect(calls.filter((c) => c.url.includes('/prompts/g1/results')).length).toBe(seen);
    await view.unmount();
  });

  it('pages with the cursor', async () => {
    const { view, calls } = await open({
      [RESULTS]: (call: { url: string }) =>
        call.url.includes('after=1')
          ? { items: [result(2, 'completed', { verdict: 'b' })], next_cursor: null }
          : { items: [result(1, 'completed', { verdict: 'a' })], next_cursor: 1 },
    });
    expect(byId(view, 'images-group-result-2')).toBeNull();
    await click(byId(view, 'images-group-results-more-g1'));
    await settle();
    expect(calls.at(-1)?.url).toContain('after=1');
    expect(byId(view, 'images-group-result-1')).not.toBeNull();
    expect(byId(view, 'images-group-result-2')).not.toBeNull();
    expect(byId(view, 'images-group-results-more-g1')).toBeNull();
    await view.unmount();
  });
});
