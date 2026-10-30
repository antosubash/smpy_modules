// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { splitList } from '../components/pipeline/ParamsForm';
import { PipelineTab } from '../components/pipeline/PipelineTab';
import { PIPELINE_POLL_MS } from '../hooks/usePipelinePoll';
import { act, click, mount, setValue } from './test-dom';
import type { PipelineOverview } from '../utils/types';
import { flush, stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());

const URL = '/api/images/collections/c1/pipeline';

function overview(overrides: Partial<PipelineOverview> = {}): PipelineOverview {
  return {
    config: { steps: {} },
    preset_id: null,
    steps: [
      {
        id: 'classify',
        installed: true,
        state: 'ok',
        enabled: false,
        params: {},
        version: 1,
        params_schema: {
          properties: { vocabulary: { type: 'array', items: { type: 'string' } } },
        },
      },
    ],
    status: {},
    stale: 0,
    not_installed: 0,
    pending: 0,
    ...overrides,
  };
}

const get = (view: { find: (s: string) => HTMLElement | null }, id: string) =>
  view.find(`[data-testid="${id}"]`);
const gets = (calls: { method: string; url: string }[]) =>
  calls.filter((c) => c.method === 'GET' && c.url === URL).length;

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('a list of strings (classify vocabulary, QA TEST-007)', () => {
  it('splits on commas and newlines, trims, drops blanks and duplicates', () => {
    expect(splitList('cropland, forest\nwater,forest\n\n , ')).toEqual([
      'cropland',
      'forest',
      'water',
    ]);
    expect(splitList('')).toEqual([]);
  });

  it('saves comma-separated labels as separate labels and says that commas work', async () => {
    const calls = stubFetch({ [`GET ${URL}`]: overview(), [`PUT ${URL}`]: () => overview() });
    const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
    await flush();
    await click(get(view, 'images-step-toggle-classify'));
    const area = view.find('#images-param-classify-vocabulary') as HTMLTextAreaElement;
    await setValue(area, 'cropland, forest,');
    expect(area.value).toBe('cropland, forest,'); // the draft keeps what is typed
    await setValue(area, 'cropland, forest,\nwater');
    expect(get(view, 'images-param-hint-classify-vocabulary')?.textContent).toBe(
      'One per line, or separated by commas.',
    );
    await click(get(view, 'images-pipeline-save'));
    await flush();
    const put = calls.find((c) => c.method === 'PUT');
    expect(put?.body).toEqual({
      steps: { classify: { enabled: true, vocabulary: ['cropland', 'forest', 'water'] } },
    });
    await view.unmount();
  });
});

describe('progress while runs are in flight (QA TEST-007)', () => {
  it('a restart that is still running does not say "Saving…", and the buttons free up when it settles', async () => {
    let finish: (() => void) | null = null;
    stubFetch({ [`GET ${URL}`]: overview() });
    // The restart answers only when the test says so (an eager host runs it inline).
    const routed = globalThis.fetch;
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') {
        await new Promise<void>((resolve) => {
          finish = resolve;
        });
        return new Response(JSON.stringify({ status: 'accepted' }), { status: 202 });
      }
      return routed(input, init);
    });
    const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
    await flush();
    await click(get(view, 'images-pipeline-restart-stale'));
    await flush();
    expect(get(view, 'images-pipeline-save')?.textContent).toBe('Save pipeline');
    expect((get(view, 'images-pipeline-restart-all') as HTMLButtonElement).disabled).toBe(true);
    await act(async () => {
      (finish as (() => void) | null)?.();
    });
    await flush();
    expect((get(view, 'images-pipeline-restart-all') as HTMLButtonElement).disabled).toBe(false);
    await view.unmount();
  });

  it('polls the counts while a run is pending or running, stops when idle, and on unmount', async () => {
    vi.useFakeTimers();
    let reads = 0;
    const calls = stubFetch({
      [`GET ${URL}`]: () => {
        reads += 1;
        if (reads < 3) return overview({ pending: 3, status: { classify: { pending: 3 } } });
        if (reads === 3) return overview({ status: { classify: { running: 1, completed: 2 } } });
        return overview({ status: { classify: { completed: 3 } } });
      },
    });
    const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
    await act(async () => vi.advanceTimersByTimeAsync(0));
    expect(gets(calls)).toBe(1);
    for (let i = 0; i < 3; i++) await act(async () => vi.advanceTimersByTimeAsync(PIPELINE_POLL_MS));
    expect(gets(calls)).toBe(4); // pending, pending, running, then idle
    await act(async () => vi.advanceTimersByTimeAsync(PIPELINE_POLL_MS * 5));
    expect(gets(calls)).toBe(4);
    await view.unmount();
  });

  it('stops polling once unmounted', async () => {
    vi.useFakeTimers();
    const calls = stubFetch({ [`GET ${URL}`]: overview({ pending: 1 }) });
    const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
    await act(async () => vi.advanceTimersByTimeAsync(0));
    await view.unmount();
    await act(async () => vi.advanceTimersByTimeAsync(PIPELINE_POLL_MS * 3));
    expect(gets(calls)).toBe(1);
  });

  it('a poll begun before a save and answered after it does not restore the older state', async () => {
    vi.useFakeTimers();
    const old = overview({ pending: 1 });
    const saved = overview({
      pending: 1,
      steps: overview().steps.map((s) => ({ ...s, enabled: true })),
    });
    stubFetch({ [`GET ${URL}`]: old, [`PUT ${URL}`]: saved });
    const routed = globalThis.fetch;
    let reads = 0;
    let answer: (() => void) | null = null;
    vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
      if ((init?.method ?? 'GET') === 'GET' && ++reads === 2) {
        const response = await routed(input, init); // the older state, read before the save
        await new Promise<void>((resolve) => {
          answer = resolve;
        });
        return response;
      }
      return routed(input, init);
    });
    const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
    await act(async () => vi.advanceTimersByTimeAsync(0));
    await act(async () => vi.advanceTimersByTimeAsync(PIPELINE_POLL_MS)); // the poll is now in flight
    await click(get(view, 'images-step-toggle-classify'));
    await click(get(view, 'images-pipeline-save'));
    await act(async () => vi.advanceTimersByTimeAsync(0));
    const toggle = () => get(view, 'images-step-toggle-classify') as HTMLInputElement;
    const before = toggle().getAttribute('aria-checked') ?? String(toggle().checked);
    await act(async () => {
      (answer as (() => void) | null)?.(); // the stale poll resolves after the save
    });
    await act(async () => vi.advanceTimersByTimeAsync(0));
    const after = toggle().getAttribute('aria-checked') ?? String(toggle().checked);
    expect(after).toBe(before);
    expect(after).toMatch(/true/);
    await view.unmount();
  });
});
