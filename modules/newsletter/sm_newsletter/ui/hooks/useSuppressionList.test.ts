// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '../utils/api';
import type { SuppressionPage } from '../utils/types';
import { PAGE_SIZE, useSuppressionList } from './useSuppressionList';

vi.mock('../utils/api', () => ({
  api: { listSuppressions: vi.fn() },
  errorMessage: () => 'failed',
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let list: ReturnType<typeof useSuppressionList>;
function Harness() {
  list = useSuppressionList();
  return null;
}

const listSuppressions = vi.mocked(api.listSuppressions);
const row = (id: number) => ({ id }) as unknown as SuppressionPage['items'][number];

describe('useSuppressionList', () => {
  beforeEach(() => {
    listSuppressions.mockReset();
    listSuppressions.mockResolvedValue({ items: [], total: 120, counts: { hard_bounce: 3 } });
  });

  async function mount() {
    const root = createRoot(document.createElement('div'));
    await act(async () => root.render(createElement(Harness)));
  }

  it('resets the offset when the reason changes', async () => {
    await mount();
    expect(list.counts).toEqual({ hard_bounce: 3 });
    await act(async () => list.setOffset(PAGE_SIZE));
    expect(listSuppressions.mock.calls.at(-1)?.[0]).toEqual({
      reason: undefined,
      offset: PAGE_SIZE,
    });
    await act(async () => list.setReason('complaint'));
    expect(list.offset).toBe(0);
    expect(listSuppressions.mock.calls.at(-1)?.[0]).toEqual({ reason: 'complaint', offset: 0 });
  });

  it('lets only the newest response win', async () => {
    await mount();
    let resolveSlow: (p: SuppressionPage) => void = () => {};
    listSuppressions.mockImplementationOnce(
      () => new Promise<SuppressionPage>((r) => (resolveSlow = r)),
    );
    listSuppressions.mockResolvedValueOnce({ items: [row(2)], total: 1, counts: {} });
    await act(async () => list.setReason('hard_bounce'));
    await act(async () => list.setReason('complaint'));
    expect(list.items?.map((i) => i.id)).toEqual([2]);
    await act(async () => resolveSlow({ items: [row(1)], total: 1, counts: {} }));
    expect(list.items?.map((i) => i.id)).toEqual([2]);
  });
});
