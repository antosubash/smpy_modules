// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { api } from '../utils/api';
import { SEARCH_DEBOUNCE_MS, useCampaignList } from './useCampaignList';

vi.mock('../utils/api', () => ({ api: { listCampaigns: vi.fn() } }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let list: ReturnType<typeof useCampaignList>;

function Harness() {
  list = useCampaignList();
  return null;
}

const listCampaigns = vi.mocked(api.listCampaigns);

describe('useCampaignList', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    listCampaigns.mockReset();
    listCampaigns.mockResolvedValue({ items: [], total: 120 });
  });
  afterEach(() => vi.useRealTimers());

  async function mount() {
    const root = createRoot(document.createElement('div'));
    await act(async () => root.render(createElement(Harness)));
    return root;
  }

  it('debounces search and resets offset', async () => {
    await mount();
    expect(listCampaigns).toHaveBeenCalledTimes(1);

    await act(async () => list.nextPage());
    expect(listCampaigns).toHaveBeenLastCalledWith(
      { q: undefined, status: undefined, offset: list.pageSize },
      expect.anything(),
    );

    listCampaigns.mockClear();
    await act(async () => list.setQ('sp'));
    await act(async () => list.setQ('spring'));
    // The offset is back at the top at once, but nothing is requested yet.
    expect(list.offset).toBe(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS - 1);
    });
    const typed = listCampaigns.mock.calls.filter(([p]) => p.q === 'spring');
    expect(typed).toHaveLength(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    const last = listCampaigns.mock.calls.at(-1);
    expect(last?.[0]).toEqual({ q: 'spring', status: undefined, offset: 0 });
    // One request for the final term, not one per keystroke.
    expect(listCampaigns.mock.calls.filter(([p]) => p.q === 'sp')).toHaveLength(0);
  });

  it('resets offset when the status changes', async () => {
    await mount();
    await act(async () => list.nextPage());
    await act(async () => list.setStatus('draft'));
    expect(list.offset).toBe(0);
    expect(listCampaigns.mock.calls.at(-1)?.[0]).toEqual({
      q: undefined,
      status: 'draft',
      offset: 0,
    });
  });

  it('steps back a page when the last row of the last page is deleted', async () => {
    listCampaigns.mockResolvedValue({ items: [], total: 51 });
    await mount();
    await act(async () => list.nextPage());
    expect(list.offset).toBe(list.pageSize);

    listCampaigns.mockResolvedValue({ items: [], total: 50 });
    await act(async () => list.reload());
    expect(list.offset).toBe(0);
    expect(listCampaigns.mock.calls.at(-1)?.[0]).toEqual({
      q: undefined,
      status: undefined,
      offset: 0,
    });
  });
});
