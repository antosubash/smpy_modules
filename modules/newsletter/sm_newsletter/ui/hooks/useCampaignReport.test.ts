// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { report } from '../components/report/fixture';
import { api } from '../utils/api';
import type { Report } from '../utils/types';
import { REPORT_POLL_MS, useCampaignReport } from './useCampaignReport';

vi.mock('../utils/api', () => ({
  api: { report: vi.fn() },
  errorMessage: () => 'shown text',
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const snap = (status: string): Report => report({ status });

let result: ReturnType<typeof useCampaignReport>;

function Harness() {
  result = useCampaignReport(7);
  return null;
}

describe('useCampaignReport', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(api.report).mockReset().mockResolvedValue(snap('sending'));
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

  it('polls every 60 seconds while sending', async () => {
    await mount();
    expect(api.report).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.report).mock.calls[0][0]).toBe(7);
    expect(result.report?.status).toBe('sending');
    await tick(REPORT_POLL_MS);
    expect(api.report).toHaveBeenCalledTimes(2);
    await tick(REPORT_POLL_MS);
    expect(api.report).toHaveBeenCalledTimes(3);
  });

  it('fetches once for a sent campaign', async () => {
    vi.mocked(api.report).mockResolvedValue(snap('sent'));
    await mount();
    await tick(REPORT_POLL_MS * 3);
    expect(api.report).toHaveBeenCalledTimes(1);
    expect(result.report?.status).toBe('sent');
  });

  it('stops polling when a poll returns sent', async () => {
    await mount();
    vi.mocked(api.report).mockResolvedValue(snap('sent'));
    await tick(REPORT_POLL_MS);
    expect(api.report).toHaveBeenCalledTimes(2);
    expect(result.report?.status).toBe('sent');
    await tick(REPORT_POLL_MS * 3);
    expect(api.report).toHaveBeenCalledTimes(2);
  });

  it('aborts and stops on unmount', async () => {
    const root = await mount();
    const signal = vi.mocked(api.report).mock.calls[0][1] as AbortSignal;
    expect(signal.aborted).toBe(false);
    await act(async () => root.unmount());
    expect(signal.aborted).toBe(true);
    await tick(REPORT_POLL_MS * 3);
    expect(api.report).toHaveBeenCalledTimes(1);
  });

  it('exposes a failure through errorMessage and clears it on success', async () => {
    vi.mocked(api.report).mockRejectedValueOnce(new Error('boom'));
    await mount();
    expect(result.error).toBe('shown text');
    expect(result.report).toBeNull();
    await act(async () => result.reload());
    expect(result.error).toBeNull();
    expect(result.report?.status).toBe('sending');
  });

  it('reload fetches now', async () => {
    vi.mocked(api.report).mockResolvedValue(snap('sent'));
    await mount();
    await act(async () => result.reload());
    expect(api.report).toHaveBeenCalledTimes(2);
  });
});
