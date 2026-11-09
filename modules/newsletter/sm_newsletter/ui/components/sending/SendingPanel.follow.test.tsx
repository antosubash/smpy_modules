// @vitest-environment happy-dom
// The panel follows the worker: when a poll reports another status than the
// page's copy, the campaign is re-read and the panel re-renders that state.
import { act, createElement, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import { PROGRESS_POLL_MS } from '../../hooks/useCampaignProgress';
import { api } from '../../utils/api';
import type { CampaignDetail } from '../../utils/types';
import { campaign, progress } from './panelFixture';
import { SendingPanel } from './SendingPanel';

vi.mock('../../utils/api', async (original) => ({
  ...(await original<typeof import('../../utils/api')>()),
  api: { progress: vi.fn(), getCampaign: vi.fn() },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = en.sending;
const labels = () => [...document.querySelectorAll('button')].map((b) => b.textContent);

/** The panel inside a parent that keeps the campaign, as the editor does. */
function Parent({ initial }: { initial: CampaignDetail }) {
  const [c, setC] = useState(initial);
  return createElement(SendingPanel, { campaign: c, canSend: true, onChange: setC });
}

describe('SendingPanel follows the worker', () => {
  let root: Root;

  beforeEach(() => {
    vi.mocked(api.progress).mockReset();
    vi.mocked(api.getCampaign).mockReset();
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  async function render(c: CampaignDetail) {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () => root.render(createElement(Parent, { initial: c })));
  }

  it('scheduled -> sending: shows the progress and Pause, not Unschedule', async () => {
    vi.mocked(api.progress).mockResolvedValue(progress());
    vi.mocked(api.getCampaign).mockResolvedValue(campaign());
    await render(campaign({ status: 'scheduled', scheduled_at: '2026-12-01T10:00:00Z' }));
    expect(api.getCampaign).toHaveBeenCalledWith(7);
    expect(document.body.textContent).toContain('100 of 300 sent');
    expect(labels()).toContain(copy.actions.pause);
    expect(labels()).not.toContain(copy.actions.unschedule);
  });

  it('sending -> sent: shows the finish date and the counts', async () => {
    vi.mocked(api.progress).mockResolvedValue(progress({ status: 'sent', skipped: 4 }));
    vi.mocked(api.getCampaign).mockResolvedValue(
      campaign({ status: 'sent', finished_at: '2026-12-01T10:00:00Z', bounced_count: 3 }),
    );
    await render(campaign());
    expect(document.body.textContent).toContain('3 bounced');
    expect(document.body.textContent).toContain('4 skipped');
    expect(labels()).toEqual([]);
  });

  it('sending -> paused: offers Resume with the translated reason and the detail', async () => {
    vi.mocked(api.progress).mockResolvedValue(progress({ status: 'paused' }));
    vi.mocked(api.getCampaign).mockResolvedValue(
      campaign({ status: 'paused', paused_code: 'smtp_rejected', paused_detail: '554 policy' }),
    );
    await render(campaign());
    expect(document.body.textContent).toContain(copy.paused_code.smtp_rejected);
    expect(document.body.textContent).toContain('554 policy');
    expect(labels()).toContain(copy.actions.resume);
    expect(labels()).not.toContain(copy.actions.pause);
  });

  it('retries a failed re-read: the poll that reported the change was the last one', async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(api.progress).mockResolvedValue(progress({ status: 'paused' }));
      vi.mocked(api.getCampaign)
        .mockRejectedValueOnce(new Error('boom'))
        .mockResolvedValue(campaign({ status: 'paused', paused_code: 'manual' }));
      await render(campaign());
      expect(api.getCampaign).toHaveBeenCalledTimes(1);
      expect(labels()).toContain(copy.actions.pause);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(PROGRESS_POLL_MS);
      });
      expect(api.getCampaign).toHaveBeenCalledTimes(2);
      expect(labels()).toContain(copy.actions.resume);
    } finally {
      vi.useRealTimers();
    }
  });

  it('re-reads nothing while the poll agrees with the page', async () => {
    vi.mocked(api.progress).mockResolvedValue(progress());
    await render(campaign());
    expect(api.getCampaign).not.toHaveBeenCalled();
  });
});
