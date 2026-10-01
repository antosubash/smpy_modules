import { describe, expect, it, vi } from 'vitest';

import { createInFlightGuard } from './inFlight';

describe('createInFlightGuard', () => {
  it('runs a burst of calls once', async () => {
    const guard = createInFlightGuard();
    let release: () => void = () => {};
    const work = vi.fn(() => new Promise<string>((r) => (release = () => r('done'))));

    const burst = [guard(work), guard(work), guard(work), guard(work), guard(work)];
    release();
    const results = await Promise.all(burst);

    expect(work).toHaveBeenCalledTimes(1);
    expect(results).toEqual(['done', undefined, undefined, undefined, undefined]);
  });

  it('mirrors busy and lets go afterwards, even on failure', async () => {
    const seen: boolean[] = [];
    const guard = createInFlightGuard((b) => seen.push(b));

    await expect(guard(() => Promise.reject(new Error('boom')))).rejects.toThrow('boom');
    expect(seen).toEqual([true, false]);

    const again = vi.fn(async () => 1);
    await guard(again);
    expect(again).toHaveBeenCalledTimes(1);
  });

  it('stays closed through the cooldown after a success, so a click burst cannot reach the next action', async () => {
    const guard = createInFlightGuard(() => {}, 40);
    const first = vi.fn(async () => 'ok');
    const second = vi.fn(async () => 'ok');

    const running = guard(first);
    // The work has finished but the guard is still cooling down.
    await new Promise((r) => setTimeout(r, 10));
    expect(await guard(second)).toBeUndefined();
    expect(second).not.toHaveBeenCalled();

    await running;
    await guard(second);
    expect(second).toHaveBeenCalledTimes(1);
  });

  it('does not cool down after a failure', async () => {
    const guard = createInFlightGuard(() => {}, 5000);
    await guard(() => Promise.reject(new Error('x'))).catch(() => {});
    const next = vi.fn(async () => 1);
    // Not awaited: this success would itself cool down for the full 5s.
    void guard(next);
    expect(next).toHaveBeenCalled();
  });
});
