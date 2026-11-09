// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import { TestSendDialog } from './TestSendDialog';

// The real client over a stubbed network, so a refusal is decoded as in production.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = en.test_send;

describe('TestSendDialog refusals', () => {
  let root: ReturnType<typeof createRoot>;
  afterEach(() => {
    vi.unstubAllGlobals();
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  const button = (label: string) =>
    [...document.querySelectorAll('button')].find((b) => b.textContent === label);

  async function refused(status: number, code: string) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: 'x', code }), { status })),
    );
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () => root.render(createElement(TestSendDialog, { campaignId: 7, max: 5 })));
    await act(async () => button(copy.trigger)?.click());
    const field = document.querySelector('textarea') as HTMLTextAreaElement;
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
      set?.call(field, 'a@x.io');
      field.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => button(copy.send)?.click());
    return document.body.textContent ?? '';
  }

  it('shows the budget message on a 429', async () => {
    expect(await refused(429, 'send_budget_exhausted')).toContain(en.errors.send_budget_exhausted);
  });

  it('shows the code message on a 422, not "invalid address"', async () => {
    const text = await refused(422, 'public_base_url_required');
    expect(text).toContain(en.errors.public_base_url_required);
    expect(text).not.toContain(copy.invalid_recipients);
  });

  it('falls back to invalid recipients on a 422 with an unknown code', async () => {
    expect(await refused(422, 'invalid_campaign_payload')).toContain(copy.invalid_recipients);
  });
});
