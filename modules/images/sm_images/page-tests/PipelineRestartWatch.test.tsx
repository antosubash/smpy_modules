// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PipelineTab, RESTART_WATCH_MS } from '../components/pipeline/PipelineTab';
import { PIPELINE_POLL_MS } from '../hooks/usePipelinePoll';
import { act, click, mount } from '../test-dom';
import type { PipelineOverview } from '../utils/types';
import { stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());

const URL = '/api/images/collections/c1/pipeline';

function overview(status: Record<string, Record<string, number>>, pending = 0): PipelineOverview {
  return {
    config: { steps: {} },
    preset_id: null,
    steps: [
      {
        id: 'prompt:646b48c4',
        label: 'Land cover',
        installed: true,
        state: 'ok',
        enabled: true,
        params: {},
        version: 1,
        params_schema: { properties: {} },
      },
    ],
    status,
    stale: 0,
    not_installed: 0,
    pending,
  };
}

const IDLE = overview({ 'prompt:646b48c4': { completed: 3 } });
const tick = () => act(async () => vi.advanceTimersByTimeAsync(PIPELINE_POLL_MS));
const gets = (calls: { method: string; url: string }[]) =>
  calls.filter((c) => c.method === 'GET' && c.url === URL).length;

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function open(reads: () => PipelineOverview) {
  vi.useFakeTimers();
  const calls = stubFetch({
    [`GET ${URL}`]: reads,
    [`POST ${URL}/restart`]: { status: 'accepted', scope: 'all' },
  });
  const view = await mount(<PipelineTab collectionId="c1" canManage={true} />);
  await act(async () => vi.advanceTimersByTimeAsync(0));
  return { view, calls };
}

describe('after a restart request (review of QA round 1)', () => {
  it('a restart during active runs keeps polling through a broker delay after they finish', async () => {
    // Review: the old runs being active ended the watch at once; when they
    // finished, polling stopped before the queued restart reset anything.
    const RUNNING = overview({ 'prompt:646b48c4': { running: 1, completed: 2 } });
    let reads = 0;
    const { view } = await open(() => {
      reads += 1;
      if (reads <= 3) return RUNNING; // the old runs
      if (reads <= 8) return IDLE; // they finished; the restart is still queued
      return overview({ 'prompt:646b48c4': { pending: 3 } }, 3); // it began
    });
    await click(view.find('[data-testid="images-pipeline-restart-all"]'));
    await act(async () => vi.advanceTimersByTimeAsync(0));
    for (let i = 0; i < 8; i++) await tick();
    expect(reads).toBeGreaterThanOrEqual(9); // polled through the idle reads
    expect(view.find('[data-testid="images-step-prompt:646b48c4"]')).not.toBeNull();
    await view.unmount();
  });

  it('a second restart renews the watch window', async () => {
    const { view, calls } = await open(() => IDLE);
    const button = () => view.find('[data-testid="images-pipeline-restart-stale"]');
    await click(button());
    await act(async () => vi.advanceTimersByTimeAsync(50_000));
    await click(button());
    await act(async () => vi.advanceTimersByTimeAsync(55_000)); // 105 s after the first
    const at105 = gets(calls);
    await act(async () => vi.advanceTimersByTimeAsync(4_000)); // 109 s: still watched
    expect(gets(calls)).toBeGreaterThan(at105);
    await act(async () => vi.advanceTimersByTimeAsync(PIPELINE_POLL_MS * 2)); // past 110 s
    const done = gets(calls);
    await act(async () => vi.advanceTimersByTimeAsync(PIPELINE_POLL_MS * 10));
    expect(gets(calls)).toBe(done);
    await view.unmount();
  });

  it('gives up once the watch window passes with nothing to show', async () => {
    const { view, calls } = await open(() => IDLE);
    await click(view.find('[data-testid="images-pipeline-restart-stale"]'));
    await act(async () => vi.advanceTimersByTimeAsync(RESTART_WATCH_MS + PIPELINE_POLL_MS * 2));
    const seen = gets(calls);
    expect(seen).toBeGreaterThan(3);
    await act(async () => vi.advanceTimersByTimeAsync(PIPELINE_POLL_MS * 10));
    expect(gets(calls)).toBe(seen);
    await view.unmount();
  });

  it('names a prompt step by its prompt in the step list', async () => {
    const { view } = await open(() => IDLE);
    const label = view.find('#images-step-label-prompt\\:646b48c4');
    expect(label?.textContent).toBe('Land cover');
    expect(label?.getAttribute('title')).toBe('prompt:646b48c4');
    await view.unmount();
  });
});
