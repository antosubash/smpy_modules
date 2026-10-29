// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { act, mount } from '../test-dom';
import { ApiError } from '../utils/api-net';
import type { RegroupJob } from '../utils/types';

const getRegroup = vi.fn();
vi.mock('../utils/api-groups', () => ({ getRegroup: (id: string) => getRegroup(id) }));

const { MAX_FAILURES, useRegroupJob } = await import('./useRegroupJob');

const running = { id: 'j1', status: 'running', scanned: 1, assigned: 0 } as RegroupJob;

function Probe({ onFinished }: { onFinished?: () => void }) {
  const { job, gone, error } = useRegroupJob('j1', onFinished);
  return (
    <output data-gone={String(gone)} data-error={error ?? ''} data-status={job?.status ?? ''} />
  );
}

const state = (view: { find: (s: string) => HTMLElement | null }) => {
  const out = view.find('output') as HTMLElement;
  return {
    gone: out.dataset.gone === 'true',
    error: out.dataset.error,
    status: out.dataset.status,
  };
};

const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });

beforeEach(() => {
  vi.useFakeTimers();
  getRegroup.mockReset();
});
afterEach(() => vi.useRealTimers());

describe('useRegroupJob', () => {
  it('stops polling when the job is gone (404) and says so', async () => {
    getRegroup.mockResolvedValueOnce(running);
    getRegroup.mockRejectedValue(new ApiError(404, null, 'Not found'));
    const finished = vi.fn();
    const view = await mount(<Probe onFinished={finished} />);
    await advance(0);
    expect(state(view).status).toBe('running');
    await advance(2000);
    expect(state(view).gone).toBe(true);
    expect(finished).toHaveBeenCalledTimes(1);
    await advance(120_000);
    expect(getRegroup).toHaveBeenCalledTimes(2);
    await view.unmount();
  });

  it('backs off on other failures and gives up with an error after ten in a row', async () => {
    getRegroup.mockRejectedValue(new ApiError(503, null, 'Unavailable'));
    const view = await mount(<Probe />);
    await advance(0);
    expect(getRegroup).toHaveBeenCalledTimes(1);
    await advance(2000); // the first retry waits 2 s
    expect(getRegroup).toHaveBeenCalledTimes(2);
    await advance(2000); // the second 4 s
    expect(getRegroup).toHaveBeenCalledTimes(2);
    await advance(2000);
    expect(getRegroup).toHaveBeenCalledTimes(3);
    expect(state(view).error).toBe('');
    await advance(10 * 30_000); // capped at 30 s
    expect(getRegroup).toHaveBeenCalledTimes(MAX_FAILURES);
    expect(state(view).error).not.toBe('');
    await advance(120_000);
    expect(getRegroup).toHaveBeenCalledTimes(MAX_FAILURES);
    await view.unmount();
  });

  it('starts counting again after a read that works', async () => {
    getRegroup.mockRejectedValueOnce(new ApiError(503, null, 'Unavailable'));
    getRegroup.mockResolvedValue(running);
    const view = await mount(<Probe />);
    await advance(0);
    await advance(2000);
    expect(state(view)).toEqual({ gone: false, error: '', status: 'running' });
    await advance(2000); // back to the plain interval
    expect(getRegroup).toHaveBeenCalledTimes(3);
    await view.unmount();
  });
});
