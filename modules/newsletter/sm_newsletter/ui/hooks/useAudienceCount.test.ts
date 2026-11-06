// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '../utils/api';
import { COUNT_DEBOUNCE_MS, useAudienceCount } from './useAudienceCount';

vi.mock('../utils/api', async (original) => ({
  ...(await original<typeof import('../utils/api')>()),
  api: { audienceCount: vi.fn() },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let audience = 'all';
let result: ReturnType<typeof useAudienceCount>;
function Harness() {
  result = useAudienceCount('news', audience);
  return null;
}

describe('useAudienceCount', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(api.audienceCount).mockReset().mockResolvedValue({ count: 5 });
    audience = 'all';
  });
  afterEach(() => vi.useRealTimers());

  async function mount() {
    const root = createRoot(document.createElement('div'));
    await act(async () => root.render(createElement(Harness)));
    return root;
  }
  const wait = (ms: number) =>
    act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });

  it('asks once per debounce and shows the count', async () => {
    const root = await mount();
    for (const next of ['tag:a', 'tag:ab', 'tag:abc']) {
      audience = next;
      await act(async () => root.render(createElement(Harness)));
      await wait(COUNT_DEBOUNCE_MS - 100);
    }
    expect(api.audienceCount).not.toHaveBeenCalled();
    await wait(COUNT_DEBOUNCE_MS);
    expect(api.audienceCount).toHaveBeenCalledTimes(1);
    expect(api.audienceCount).toHaveBeenCalledWith('news', 'tag:abc', expect.any(AbortSignal));
    expect(result).toEqual({ count: 5, error: null, loading: false });
  });

  it('a stale answer never overwrites a newer count', async () => {
    let first: (v: { count: number }) => void = () => {};
    vi.mocked(api.audienceCount)
      .mockImplementationOnce(
        () =>
          new Promise((r) => {
            first = r;
          }),
      )
      .mockResolvedValueOnce({ count: 9 });
    const root = await mount();
    await wait(COUNT_DEBOUNCE_MS);
    const signal = vi.mocked(api.audienceCount).mock.calls[0][2] as AbortSignal;
    audience = 'tag:vip';
    await act(async () => root.render(createElement(Harness)));
    expect(signal.aborted).toBe(true);
    await wait(COUNT_DEBOUNCE_MS);
    expect(result.count).toBe(9);
    await act(async () => first({ count: 1 }));
    expect(result.count).toBe(9);
  });

  it('asks for nothing without an audience', async () => {
    audience = '';
    await mount();
    await wait(COUNT_DEBOUNCE_MS * 2);
    expect(api.audienceCount).not.toHaveBeenCalled();
    expect(result.count).toBeNull();
  });
});
