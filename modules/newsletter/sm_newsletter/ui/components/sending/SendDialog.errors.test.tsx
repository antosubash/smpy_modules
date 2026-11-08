// @vitest-environment happy-dom
// SendDialog's refusals: which message shows, and that one goes once it no longer applies.
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import de from '../../../locales/de.json';
import en from '../../../locales/en.json';
import { campaign } from '../../hooks/campaignFixture';
import { api } from '../../utils/api';
import { HttpError } from '../../utils/http';
import { SendDialog } from './SendDialog';

vi.mock('../../utils/api', async (original) => ({
  ...(await original<typeof import('../../utils/api')>()),
  api: { estimate: vi.fn(), sendCampaign: vi.fn() },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = en.sending;
const estimate = vi.mocked(api.estimate);
const sendCampaign = vi.mocked(api.sendCampaign);
const DAY = 86_400_000;
const figures = {
  recipients: 42,
  estimated_finish: '2026-12-01T10:00:00Z',
  overlaps: false,
  daily_rate: 100,
};

/** A `datetime-local` value `days` from now, in the browser's local time. */
function localIn(days: number): string {
  const d = new Date(Date.now() + days * DAY);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const button = (label: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent === label) as
    | HTMLButtonElement
    | undefined;
const alertText = () => document.querySelector('[role="alert"]')?.textContent ?? null;

describe('SendDialog refusals', () => {
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    estimate.mockReset().mockResolvedValue(figures);
    sendCampaign.mockReset();
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  async function open() {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    const props = {
      campaign: campaign(3),
      canSend: true,
      onSent: vi.fn(),
      flush: vi.fn().mockResolvedValue(true),
      dirty: false,
      incomplete: false,
      currentRevision: () => 5,
    };
    await act(async () => root.render(createElement(SendDialog, props)));
    await act(async () => button(copy.send_button)?.click());
  }

  async function choose(id: 'now' | 'later') {
    const radio = document.querySelector(`[role="radio"][value="${id}"]`) as HTMLElement;
    await act(async () => radio.click());
  }

  async function later(value: string) {
    await choose('later');
    const field = document.querySelector('input[type="datetime-local"]') as HTMLInputElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(field, value);
      field.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  it('drops a failed estimate once the time changes and a valid estimate arrives', async () => {
    await open();
    estimate.mockRejectedValueOnce(new HttpError('x', 422, 'invalid_campaign'));
    await later(localIn(30));
    expect(alertText()).toBe(en.errors.invalid_campaign);
    await later(localIn(31));
    expect(alertText()).toBeNull();
    expect(document.body.textContent).toContain('42 recipients');
  });

  it('drops a failed estimate when switching to "Send now" and back', async () => {
    await open();
    estimate.mockRejectedValueOnce(new HttpError('x', 422, 'invalid_campaign'));
    await later(localIn(30));
    expect(alertText()).not.toBeNull();
    await choose('now');
    expect(alertText()).toBeNull();
    await choose('later');
    expect(alertText()).toBeNull();
  });

  it('refuses a time more than a year ahead with its own message, without asking for an estimate', async () => {
    await open();
    estimate.mockClear();
    await later(localIn(400));
    expect(document.body.textContent).toContain(copy.dialog.time_far);
    expect(document.body.textContent).not.toContain(copy.dialog.time_past);
    expect(estimate).not.toHaveBeenCalled();
    expect(button(copy.dialog.confirm)?.disabled).toBe(true);
    await later(localIn(300));
    expect(document.body.textContent).not.toContain(copy.dialog.time_far);
    expect(estimate).toHaveBeenCalledTimes(1);
  });

  it('takes a time just inside the 366-day horizon and refuses one just past it', async () => {
    const MINUTE = 1 / 1440;
    await open();
    await later(localIn(366 - 2 * MINUTE));
    expect(document.body.textContent).not.toContain(copy.dialog.time_far);
    await later(localIn(366 + 2 * MINUTE));
    expect(document.body.textContent).toContain(copy.dialog.time_far);
  });

  it("drops a refused send's message as soon as the time is changed", async () => {
    sendCampaign.mockRejectedValue(new HttpError('x', 409, 'invalid_campaign'));
    await open();
    await later(localIn(30));
    await act(async () => button(copy.dialog.confirm)?.click());
    expect(alertText()).not.toBeNull();
    await later(localIn(31));
    expect(alertText()).toBeNull();
  });

  it('says to add a subject when the send is refused for a missing one', async () => {
    sendCampaign.mockRejectedValue(new HttpError('subject: required', 422, 'invalid_campaign'));
    await open();
    await act(async () => button(copy.dialog.confirm)?.click());
    expect(alertText()).toBe(en.errors_field.subject_required);
    expect(de.errors_field.subject_required).toBeTruthy();
  });
});
