// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import type { Suppression } from '../../utils/types';
import { LiftDialog } from './LiftDialog';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = en.suppressions.lift;

const make = (reason: Suppression['reason']): Suppression => ({
  id: 7,
  fingerprint: 'fp7',
  reason,
  list_type_key: reason === 'unsubscribed' ? 'news' : '',
  source: 'send',
  created_at: '2026-11-01T10:00:00Z',
  version: 'ver-abc',
  liftable: true,
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('LiftDialog', () => {
  let root: ReturnType<typeof createRoot>;
  let fetchMock: ReturnType<typeof vi.fn>;
  let next: () => Response;
  const onLifted = vi.fn();
  const onStale = vi.fn();
  const onOpenChange = vi.fn();

  beforeEach(() => {
    onLifted.mockReset();
    onStale.mockReset();
    onOpenChange.mockReset();
    next = () => json({ id: 1 });
    fetchMock = vi.fn(async () => next());
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  async function open(reason: Suppression['reason'], knownEmail?: string) {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () =>
      root.render(
        createElement(LiftDialog, {
          suppression: make(reason),
          knownEmail,
          open: true,
          onOpenChange,
          onLifted,
          onStale,
        }),
      ),
    );
  }
  const email = () => document.querySelector('input[type="email"]') as HTMLInputElement;
  const note = () => document.querySelector('textarea') as HTMLTextAreaElement;
  const confirm = () =>
    [...document.querySelectorAll('button')].find((b) => b.textContent === copy.confirm) as
      | HTMLButtonElement
      | undefined;
  function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement : HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(proto.prototype, 'value')?.set;
    act(() => {
      setter?.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }

  it('never pre-fills the email of a hard bounce', async () => {
    await open('hard_bounce', 'a@example.com');
    expect(email().value).toBe('');
    expect(document.body.textContent).toContain(copy.hard_bounce_warning);
  });

  it('pre-fills a cleaned address from the known email', async () => {
    await open('imported_cleaned', 'a@example.com');
    expect(email().value).toBe('a@example.com');
    expect(document.body.textContent).toContain(copy.cleaned_hint);
  });

  it('warns that an unsubscribed address opted out', async () => {
    await open('unsubscribed', 'a@example.com');
    expect(email().value).toBe('a@example.com');
    expect(document.body.textContent).toContain(copy.opt_out_warning);
  });

  it('disables confirm until the email and the note are filled', async () => {
    await open('hard_bounce');
    expect(confirm()?.disabled).toBe(true);
    type(email(), 'a@example.com');
    expect(confirm()?.disabled).toBe(true);
    type(note(), 'mailbox works again');
    expect(confirm()?.disabled).toBe(false);
  });

  it('posts the version of the row it was opened on', async () => {
    await open('imported_cleaned', 'a@example.com');
    type(note(), 'verified by phone');
    await act(async () => confirm()?.click());
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe('/api/newsletter/suppressions/7/lift');
    expect(JSON.parse(String(init.body))).toEqual({
      version: 'ver-abc',
      email: 'a@example.com',
      note: 'verified by phone',
    });
    expect(onLifted).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('closes on suppression_changed and hands the message to the page', async () => {
    next = () => json({ detail: 'x', code: 'suppression_changed' }, 409);
    await open('imported_cleaned', 'a@example.com');
    type(note(), 'n');
    await act(async () => confirm()?.click());
    expect(onStale).toHaveBeenCalledWith(en.errors.suppression_changed);
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onLifted).not.toHaveBeenCalled();
  });

  it('shows opt_out_stands and does not report a lift', async () => {
    next = () => json({ detail: 'x', code: 'opt_out_stands' }, 409);
    await open('unsubscribed', 'a@example.com');
    type(note(), 'n');
    await act(async () => confirm()?.click());
    expect(document.body.textContent).toContain(en.errors.opt_out_stands);
    expect(onLifted).not.toHaveBeenCalled();
    expect(onStale).not.toHaveBeenCalled();
  });
});
