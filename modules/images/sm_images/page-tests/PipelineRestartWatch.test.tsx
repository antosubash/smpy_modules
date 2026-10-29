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
  it('keeps polling through a broker delay until the restart shows, then until idle', async () => {
    let restarted = false;
    let after = 0;
    const { view, calls } = await open(() => {
      if (!restarted) return IDLE;
      after += 1; // the re-read on return, then the polls
      if (after <= 3) return IDLE; // queued on the broker: nothing reset yet
      if (after === 4) return overview({ 'prompt:646b48c4': { pending: 3 } }, 3);
      return IDLE;
    });
    restarted = true;
    await click(view.find('[data-testid="images-pipeline-restart-all"]'));
    await act(async () => vi.advanceTimersByTimeAsync(0));
    const start = gets(calls);
    for (let i = 0; i < 4; i++) await tick();
    expect(gets(calls)).toBe(start + 4); // idle, idle, pending, idle
    await act(async () => vi.advanceTimersByTimeAsync(PIPELINE_POLL_MS * 5));
    expect(gets(calls)).toBe(start + 4); // done: stopped
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
