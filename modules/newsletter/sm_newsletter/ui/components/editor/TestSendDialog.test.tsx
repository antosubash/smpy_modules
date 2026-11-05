// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import { api } from '../../utils/api';
import { TestSendDialog } from './TestSendDialog';

vi.mock('../../utils/api', () => ({
  api: { testSend: vi.fn() },
  errorMessage: () => 'failed',
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = en.test_send;

describe('TestSendDialog', () => {
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => vi.mocked(api.testSend).mockReset());
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
  });

  const button = (label: string) =>
    [...document.querySelectorAll('button')].find((b) => b.textContent === label);

  async function open(beforeSend?: () => Promise<boolean>) {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () =>
      root.render(createElement(TestSendDialog, { campaignId: 7, max: 5, beforeSend })),
    );
    await act(async () => button(copy.trigger)?.click());
  }

  async function type(value: string) {
    const field = document.querySelector('textarea') as HTMLTextAreaElement;
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
      set?.call(field, value);
      field.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  it('refuses a sixth address client-side', async () => {
    await open();
    await type('a@x.io, b@x.io\nc@x.io, d@x.io, e@x.io, f@x.io, A@x.io');
    expect((button(copy.send) as HTMLButtonElement).disabled).toBe(true);
    expect(document.body.textContent).toContain('at most 5');
    await act(async () => button(copy.send)?.click());
    expect(api.testSend).not.toHaveBeenCalled();
  });

  it('shows per-recipient results', async () => {
    vi.mocked(api.testSend).mockResolvedValue({
      results: [
        { recipient: 'a@x.io', outcome: 'accepted', code: 250, detail: '' },
        { recipient: 'b@x.io', outcome: 'rejected', code: 550, detail: 'no' },
      ],
    });
    const beforeSend = vi.fn().mockResolvedValue(true);
    await open(beforeSend);
    await type('a@x.io\nb@x.io');
    await act(async () => button(copy.send)?.click());
    expect(beforeSend).toHaveBeenCalled();
    expect(api.testSend).toHaveBeenCalledWith(7, ['a@x.io', 'b@x.io']);
    const rows = [...document.querySelectorAll('li')].map((li) => li.textContent);
    expect(rows).toEqual([`a@x.io${copy.outcome.accepted}`, `b@x.io${copy.outcome.rejected}`]);
  });

  it('does not send when the draft could not be saved', async () => {
    await open(() => Promise.resolve(false));
    await type('a@x.io');
    await act(async () => button(copy.send)?.click());
    expect(api.testSend).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain(copy.unsaved);
  });
});
