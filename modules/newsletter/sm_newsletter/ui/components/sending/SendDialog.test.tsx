// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import { campaign as baseCampaign } from '../../hooks/campaignFixture';
import { api } from '../../utils/api';
import { HttpError } from '../../utils/http';
import { toUtcIso } from '../../utils/progress';
import type { CampaignDetail } from '../../utils/types';
import { SendDialog } from './SendDialog';

vi.mock('../../utils/api', async (original) => ({
  ...(await original<typeof import('../../utils/api')>()),
  api: { estimate: vi.fn(), sendCampaign: vi.fn() },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = en.sending;
const estimate = vi.mocked(api.estimate);
const sendCampaign = vi.mocked(api.sendCampaign);

function campaign(over: Partial<CampaignDetail> = {}): CampaignDetail {
  return { ...baseCampaign(3), ...over };
}

type Props = Parameters<typeof SendDialog>[0];

const button = (label: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent === label) as
    | HTMLButtonElement
    | undefined;

describe('SendDialog', () => {
  let root: ReturnType<typeof createRoot>;
  let props: Props;

  beforeEach(() => {
    estimate.mockReset().mockResolvedValue({
      recipients: 42,
      estimated_finish: '2026-12-01T10:00:00Z',
      overlaps: false,
      daily_rate: 100,
    });
    sendCampaign.mockReset().mockResolvedValue(campaign({ status: 'sending', revision: 6 }));
    props = {
      campaign: campaign(),
      canSend: true,
      onSent: vi.fn(),
      flush: vi.fn().mockResolvedValue(true),
      dirty: false,
      incomplete: false,
      currentRevision: () => 5,
    };
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  async function render(over: Partial<Props> = {}) {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () => root.render(createElement(SendDialog, { ...props, ...over })));
  }

  async function open(over: Partial<Props> = {}) {
    await render(over);
    await act(async () => button(copy.send_button)?.click());
  }

  async function later(value: string) {
    const radio = document.querySelector('[role="radio"][value="later"]') as HTMLElement;
    await act(async () => radio.click());
    const field = document.querySelector('input[type="datetime-local"]') as HTMLInputElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(field, value);
      field.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  it('is hidden without can_send, and for a campaign that is not a draft', async () => {
    await render({ canSend: false });
    expect(button(copy.send_button)).toBeUndefined();
    await act(async () =>
      root.render(
        createElement(SendDialog, { ...props, campaign: campaign({ status: 'scheduled' }) }),
      ),
    );
    expect(button(copy.send_button)).toBeUndefined();
  });

  it('is disabled while a block is unfinished', async () => {
    await render({ incomplete: true });
    expect(button(copy.send_button)?.disabled).toBe(true);
    expect(document.body.textContent).toContain(en.sending.dialog.incomplete);
  });

  it('flushes on open, then loads the estimate and shows the recipients', async () => {
    await open();
    expect(props.flush).toHaveBeenCalledTimes(1);
    expect(estimate).toHaveBeenCalledWith(7, null);
    expect(document.body.textContent).toContain('42 recipients');
    expect(document.body.textContent).not.toContain(copy.dialog.overlap);
  });

  it('sends now with the revision of the final save, and reports the campaign', async () => {
    await open();
    await act(async () => button(copy.dialog.confirm)?.click());
    expect(props.flush).toHaveBeenCalledTimes(2);
    expect(sendCampaign).toHaveBeenCalledWith(7, { expected_revision: 5, scheduled_at: null });
    expect(props.onSent).toHaveBeenCalledWith(expect.objectContaining({ status: 'sending' }));
  });

  it('refuses an empty or past time for later, and posts a future one in UTC', async () => {
    await open();
    await later('');
    expect(button(copy.dialog.confirm)?.disabled).toBe(true);
    await later('2020-01-01T09:00');
    expect(button(copy.dialog.confirm)?.disabled).toBe(true);
    expect(document.body.textContent).toContain(copy.dialog.time_past);
    // No estimate for a time that cannot be scheduled.
    expect(document.body.textContent).not.toContain('42 recipients');
    await act(async () => button(copy.dialog.confirm)?.click());
    expect(sendCampaign).not.toHaveBeenCalled();

    await later('2099-01-01T09:00');
    const iso = toUtcIso('2099-01-01T09:00');
    expect(estimate).toHaveBeenLastCalledWith(7, iso);
    expect(button(copy.dialog.confirm)?.disabled).toBe(false);
    await act(async () => button(copy.dialog.confirm)?.click());
    expect(sendCampaign).toHaveBeenCalledWith(7, { expected_revision: 5, scheduled_at: iso });
  });

  it('warns when the send overlaps another one', async () => {
    estimate.mockResolvedValue({
      recipients: 3,
      estimated_finish: '2026-12-01T10:00:00Z',
      overlaps: true,
      daily_rate: 100,
    });
    await open();
    expect(document.body.textContent).toContain(copy.dialog.overlap);
  });

  it('tells the writer to reload on a 409 stale', async () => {
    sendCampaign.mockRejectedValue(new HttpError('stale', 409, 'stale'));
    await open();
    await act(async () => button(copy.dialog.confirm)?.click());
    expect(document.body.textContent).toContain(en.errors.stale);
    expect(props.onSent).not.toHaveBeenCalled();
  });

  it('posts nothing when the edits could not be saved', async () => {
    const flush = vi.fn().mockResolvedValueOnce(true).mockResolvedValue(false);
    await open({ flush });
    await act(async () => button(copy.dialog.confirm)?.click());
    expect(flush).toHaveBeenCalledTimes(2);
    expect(sendCampaign).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain(en.sending.dialog.unsaved);
  });

  it('stops at open when the edits could not be saved', async () => {
    await open({ flush: vi.fn().mockResolvedValue(false) });
    expect(estimate).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain(en.sending.dialog.unsaved);
    expect(button(copy.dialog.confirm)?.disabled).toBe(true);
  });

  it('keeps Confirm disabled until the estimate has loaded', async () => {
    let answer: (e: Awaited<ReturnType<typeof api.estimate>>) => void = () => {};
    estimate.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    await open();
    expect(button(copy.dialog.confirm)?.disabled).toBe(true);
    await act(async () =>
      answer({
        recipients: 1,
        estimated_finish: '2026-12-01T10:00:00Z',
        overlaps: false,
        daily_rate: 1,
      }),
    );
    expect(button(copy.dialog.confirm)?.disabled).toBe(false);
  });

  it('never sends now when the later time slips into the past during the save', async () => {
    const start = Date.now();
    vi.useFakeTimers({ toFake: ['Date'], now: start });
    try {
      let saved: (ok: boolean) => void = () => {};
      const flush = vi
        .fn()
        .mockResolvedValueOnce(true)
        .mockReturnValueOnce(new Promise<boolean>((resolve) => (saved = resolve)));
      await open({ flush });
      const soon = new Date(start + 60_000);
      const pad = (n: number) => String(n).padStart(2, '0');
      await later(
        `${soon.getFullYear()}-${pad(soon.getMonth() + 1)}-${pad(soon.getDate())}T${pad(soon.getHours())}:${pad(soon.getMinutes())}`,
      );
      expect(button(copy.dialog.confirm)?.disabled).toBe(false);
      await act(async () => button(copy.dialog.confirm)?.click());
      vi.setSystemTime(start + 5 * 60_000);
      await act(async () => saved(true));
      expect(sendCampaign).not.toHaveBeenCalled();
      expect(document.body.textContent).toContain(copy.dialog.time_past);
    } finally {
      vi.useRealTimers();
    }
  });

  it('opens on "Send now" again after a later time was chosen and the dialog closed', async () => {
    await open();
    await later('2099-01-01T09:00');
    await act(async () => button(copy.dialog.cancel)?.click());
    await act(async () => button(copy.send_button)?.click());
    const now = document.querySelector('[role="radio"][value="now"]');
    expect(now?.getAttribute('aria-checked')).toBe('true');
    expect(document.querySelector('input[type="datetime-local"]')).toBeNull();
    await act(async () => button(copy.dialog.confirm)?.click());
    expect(sendCampaign).toHaveBeenCalledWith(7, { expected_revision: 5, scheduled_at: null });
  });

  it('says "1 recipient" for one', async () => {
    estimate.mockResolvedValue({
      recipients: 1,
      estimated_finish: '2026-12-01T10:00:00Z',
      overlaps: false,
      daily_rate: 100,
    });
    await open();
    expect(document.body.textContent).toContain('1 recipient');
    expect(document.body.textContent).not.toContain('1 recipients');
  });
});
