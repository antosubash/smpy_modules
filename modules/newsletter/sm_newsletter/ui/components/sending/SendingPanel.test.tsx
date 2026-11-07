// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import { api } from '../../utils/api';
import { HttpError } from '../../utils/http';
import type { CampaignDetail } from '../../utils/types';
import { campaign, progress } from './panelFixture';
import { SendingPanel } from './SendingPanel';

vi.mock('../../utils/api', async (original) => ({
  ...(await original<typeof import('../../utils/api')>()),
  api: {
    progress: vi.fn(),
    getCampaign: vi.fn(),
    pauseCampaign: vi.fn(),
    resumeCampaign: vi.fn(),
    cancelCampaign: vi.fn(),
    unscheduleCampaign: vi.fn(),
  },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = en.sending;

const button = (label: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent === label) as
    | HTMLButtonElement
    | undefined;

describe('SendingPanel', () => {
  let root: ReturnType<typeof createRoot>;
  let host: HTMLElement;
  const onChange = vi.fn();

  beforeEach(() => {
    onChange.mockReset();
    vi.mocked(api.progress).mockReset().mockResolvedValue(progress());
    vi.mocked(api.unscheduleCampaign).mockReset();
    for (const fn of [api.pauseCampaign, api.resumeCampaign, api.cancelCampaign]) {
      vi.mocked(fn)
        .mockReset()
        .mockResolvedValue(campaign({ status: 'paused' }));
    }
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  async function render(c: CampaignDetail, canSend = true) {
    host = document.body.appendChild(document.createElement('div'));
    root = createRoot(host);
    await act(async () =>
      root.render(createElement(SendingPanel, { campaign: c, canSend, onChange })),
    );
  }

  it('renders nothing for a draft', async () => {
    await render(campaign({ status: 'draft' }));
    expect(host.innerHTML).toBe('');
  });

  it('shows progress and the ETA while sending, and pauses', async () => {
    await render(campaign());
    expect(host.textContent).toContain('100 of 300 sent');
    expect(host.textContent).toContain('Estimated finish: ');
    expect(host.textContent).not.toContain('per day');
    await act(async () => button(copy.actions.pause)?.click());
    expect(api.pauseCampaign).toHaveBeenCalledWith(7);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ status: 'paused' }));
  });

  it('gives the ETA without a days-at-rate parenthetical, even with one day left', async () => {
    vi.mocked(api.progress).mockResolvedValue(progress({ queued: 40, sending: 0 }));
    await render(campaign());
    expect(host.textContent).toContain('Estimated finish: ');
    expect(host.textContent).not.toContain('(');
  });

  it.each([
    ['sent', {}],
    ['cancelled', {}],
    ['paused', { started_at: '2026-11-05T12:00:00Z' }],
  ] as const)('shows how many were sent for a %s campaign', async (status, over) => {
    vi.mocked(api.progress).mockResolvedValue(progress({ status }));
    await render(campaign({ status, sent_count: 120, recipient_count: 300, ...over }));
    expect(host.textContent).toContain('120 of 300 sent');
  });

  it('shows no sent count for a paused campaign that never started', async () => {
    vi.mocked(api.progress).mockResolvedValue(progress({ status: 'paused' }));
    await render(campaign({ status: 'paused', sent_count: 0, started_at: null }));
    expect(host.textContent).not.toContain(' sent');
  });

  it('offers Resume for a paused campaign, with the reason translated and the detail shown', async () => {
    vi.mocked(api.progress).mockResolvedValue(progress({ status: 'paused' }));
    await render(
      campaign({ status: 'paused', paused_code: 'smtp_auth', paused_detail: '535 bad login' }),
    );
    expect(host.textContent).toContain(copy.paused_code.smtp_auth);
    expect(host.textContent).toContain('535 bad login');
    expect(button(copy.actions.pause)).toBeUndefined();
    await act(async () => button(copy.actions.resume)?.click());
    expect(api.resumeCampaign).toHaveBeenCalledWith(7);
  });

  it('translates the https_required pause', async () => {
    vi.mocked(api.progress).mockResolvedValue(progress({ status: 'paused' }));
    await render(
      campaign({ status: 'paused', paused_code: 'https_required', paused_detail: null }),
    );
    expect(host.textContent).toContain(copy.paused_code.https_required);
    expect(host.textContent).not.toContain('https_required');
  });

  it('asks before cancelling, and posts only after the confirmation', async () => {
    await render(campaign());
    await act(async () => button(copy.actions.cancel)?.click());
    expect(document.body.textContent).toContain(copy.cancel_confirm.title);
    expect(api.cancelCampaign).not.toHaveBeenCalled();
    const dialog = document.querySelector('[role="alertdialog"]') as HTMLElement;
    const confirm = [...dialog.querySelectorAll('button')].find(
      (b) => b.textContent === copy.cancel_confirm.confirm,
    );
    await act(async () => confirm?.click());
    expect(api.cancelCampaign).toHaveBeenCalledWith(7);
    expect(onChange).toHaveBeenCalled();
  });

  it('keeps the cancel confirmation open, with the error, when the cancel is refused', async () => {
    vi.mocked(api.cancelCampaign).mockRejectedValue(new HttpError('no', 409, 'invalid_transition'));
    await render(campaign());
    await act(async () => button(copy.actions.cancel)?.click());
    const dialog = document.querySelector('[role="alertdialog"]') as HTMLElement;
    const confirm = [...dialog.querySelectorAll('button')].find(
      (b) => b.textContent === copy.cancel_confirm.confirm,
    );
    await act(async () => confirm?.click());
    expect(onChange).not.toHaveBeenCalled();
    const still = document.querySelector('[role="alertdialog"]');
    expect(still?.textContent).toContain(en.errors.invalid_transition);
  });

  it('unschedules a scheduled campaign with its revision', async () => {
    vi.mocked(api.unscheduleCampaign).mockResolvedValue(campaign({ status: 'draft' }));
    vi.mocked(api.progress).mockResolvedValue(progress({ status: 'scheduled' }));
    await render(campaign({ status: 'scheduled', scheduled_at: '2026-12-01T10:00:00Z' }));
    await act(async () => button(copy.actions.unschedule)?.click());
    expect(api.unscheduleCampaign).toHaveBeenCalledWith(7, 3);
  });

  it('offers Unschedule for a paused campaign that never started', async () => {
    vi.mocked(api.unscheduleCampaign).mockResolvedValue(campaign({ status: 'draft' }));
    vi.mocked(api.progress).mockResolvedValue(progress({ status: 'paused' }));
    await render(campaign({ status: 'paused', paused_code: 'https_required', started_at: null }));
    expect(button(copy.actions.resume)).toBeDefined();
    expect(button(copy.actions.cancel)).toBeDefined();
    await act(async () => button(copy.actions.unschedule)?.click());
    expect(api.unscheduleCampaign).toHaveBeenCalledWith(7, 3);
  });

  it('offers no Unschedule for a paused campaign that started', async () => {
    vi.mocked(api.progress).mockResolvedValue(progress({ status: 'paused' }));
    await render(campaign({ status: 'paused', started_at: '2026-11-05T12:00:00Z' }));
    expect(button(copy.actions.resume)).toBeDefined();
    expect(button(copy.actions.unschedule)).toBeUndefined();
  });

  it('shows no action without can_send', async () => {
    await render(campaign(), false);
    expect(host.textContent).toContain('100 of 300 sent');
    expect(host.querySelectorAll('button')).toHaveLength(0);
  });

  it('shows the counts of a sent campaign', async () => {
    vi.mocked(api.progress).mockResolvedValue(
      progress({ status: 'sent', queued: 0, sending: 0, sent: 290, skipped: 4 }),
    );
    await render(
      campaign({
        status: 'sent',
        finished_at: '2026-12-01T10:00:00Z',
        failed_count: 2,
        bounced_count: 3,
        suppressed_count: 1,
        unsubscribe_count: 5,
      }),
    );
    for (const text of ['2 failed', '3 bounced', '1 suppressed', '4 skipped', '5 unsubscribed']) {
      expect(host.textContent).toContain(text);
    }
    expect(host.querySelectorAll('button')).toHaveLength(0);
  });
});
