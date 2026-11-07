// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '../utils/api';
import type { Progress } from '../utils/types';
import { PROGRESS_POLL_MS, useCampaignProgress } from './useCampaignProgress';

vi.mock('../utils/api', () => ({
  api: { progress: vi.fn() },
  errorMessage: () => 'shown text',
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const snap = (status: string): Progress => ({
  status,
  recipients: 10,
  queued: 5,
  sending: 0,
  sent: 5,
  failed: 0,
  bounced: 0,
  suppressed: 0,
  skipped: 0,
  cancelled: 0,
  paused_code: null,
  paused_detail: null,
  scheduled_at: null,
  started_at: null,
  finished_at: null,
  estimated_finish: null,
  daily_rate: 100,
});

let status: string | undefined;
let result: ReturnType<typeof useCampaignProgress>;

function Harness() {
  result = useCampaignProgress(7, status);
  return null;
}

describe('useCampaignProgress', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(api.progress).mockReset().mockResolvedValue(snap('sending'));
  });
  afterEach(() => vi.useRealTimers());

  async function mount() {
    const root = createRoot(document.createElement('div'));
    await act(async () => root.render(createElement(Harness)));
    return root;
  }
  const tick = (ms: number) =>
    act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });

  it('polls every 10 seconds while sending', async () => {
    status = 'sending';
    await mount();
    expect(api.progress).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.progress).mock.calls[0][0]).toBe(7);
    expect(result.progress?.status).toBe('sending');
    await tick(PROGRESS_POLL_MS);
    expect(api.progress).toHaveBeenCalledTimes(2);
    await tick(PROGRESS_POLL_MS);
    expect(api.progress).toHaveBeenCalledTimes(3);
  });

  it('polls a scheduled campaign too', async () => {
    status = 'scheduled';
    await mount();
    await tick(PROGRESS_POLL_MS);
    expect(api.progress).toHaveBeenCalledTimes(2);
  });

  it('fetches once for a sent campaign', async () => {
    status = 'sent';
    vi.mocked(api.progress).mockResolvedValue(snap('sent'));
    await mount();
    await tick(PROGRESS_POLL_MS * 3);
    expect(api.progress).toHaveBeenCalledTimes(1);
    expect(result.progress?.status).toBe('sent');
  });

  it('stops polling when a poll returns sent', async () => {
    status = 'sending';
    await mount();
    vi.mocked(api.progress).mockResolvedValue(snap('sent'));
    await tick(PROGRESS_POLL_MS);
    expect(api.progress).toHaveBeenCalledTimes(2);
    expect(result.progress?.status).toBe('sent');
    await tick(PROGRESS_POLL_MS * 3);
    expect(api.progress).toHaveBeenCalledTimes(2);
  });

  it('aborts and stops on unmount', async () => {
    status = 'sending';
    const root = await mount();
    const signal = vi.mocked(api.progress).mock.calls[0][1] as AbortSignal;
    expect(signal.aborted).toBe(false);
    await act(async () => root.unmount());
    expect(signal.aborted).toBe(true);
    await tick(PROGRESS_POLL_MS * 3);
    expect(api.progress).toHaveBeenCalledTimes(1);
  });

  it('exposes a failure through errorMessage and clears it on success', async () => {
    status = 'sending';
    vi.mocked(api.progress).mockRejectedValueOnce(new Error('boom'));
    await mount();
    expect(result.error).toBe('shown text');
    await tick(PROGRESS_POLL_MS);
    expect(result.error).toBeNull();
  });
});
