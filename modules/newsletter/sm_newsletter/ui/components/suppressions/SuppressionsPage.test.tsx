// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import Suppressions from '../../../pages/Suppressions';
import type { Suppression } from '../../utils/types';

vi.mock('@inertiajs/react', () => ({ Head: () => null }));
vi.mock('@simple-module-py/ui/components/PageShell', () => ({
  PageShell: ({ children }: { children: unknown }) => createElement('div', null, children as never),
}));
vi.mock('@simple-module-py/ui/layouts/AuthenticatedLayout', () => ({
  AuthenticatedLayout: () => null,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = en.suppressions;
const ADA = 'ada@example.org';
const row: Suppression = {
  id: 7,
  fingerprint: 'fp7',
  reason: 'imported_cleaned',
  list_type_key: '',
  source: 'import',
  created_at: '2026-11-01T10:00:00Z',
  version: 'v1',
  liftable: true,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('Suppressions page', () => {
  let root: ReturnType<typeof createRoot>;
  let lift: () => Response;
  let lookup: () => Promise<Response>;

  beforeEach(() => {
    lift = () => json({ id: 1 });
    lookup = async () => json([row]);
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.includes('/lookup')) return lookup();
        if (url.endsWith('/lift')) return lift();
        return json({ items: [row], total: 1, counts: { imported_cleaned: 1 } });
      }),
    );
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  const flush = () =>
    act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
  const button = (label: string) =>
    [...document.querySelectorAll('button')].find((b) => b.textContent === label);
  function type(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement : HTMLInputElement;
    act(() => {
      Object.getOwnPropertyDescriptor(proto.prototype, 'value')?.set?.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    });
  }
  async function render() {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () => root.render(createElement(Suppressions)));
    await flush();
  }
  async function runLookup() {
    type(document.getElementById('newsletter-suppressions-lookup') as HTMLInputElement, ADA);
    await act(async () => button(copy.lookup_submit)?.click());
    await flush();
  }
  async function liftIt() {
    await act(async () => button(copy.lift.action)?.click());
    type(document.getElementById('newsletter-lift-email') as HTMLInputElement, ADA);
    type(document.getElementById('newsletter-lift-note') as HTMLTextAreaElement, 'checked');
    await act(async () => button(copy.lift.confirm)?.click());
    await flush();
  }

  it('confirms a successful lift', async () => {
    await render();
    await liftIt();
    expect(document.querySelector('[role="status"]')?.textContent).toBe(copy.lift.done);
    expect(document.getElementById('newsletter-lift-note')).toBeNull();
  });

  it('closes the dialog on suppression_changed and says why', async () => {
    lift = () => json({ detail: 'x', code: 'suppression_changed' }, 409);
    await render();
    await liftIt();
    expect(document.getElementById('newsletter-lift-note')).toBeNull();
    expect(document.body.textContent).toContain(en.errors.suppression_changed);
  });

  it('does not bring back a lookup cleared while its refresh was in flight', async () => {
    await render();
    await runLookup();
    let answer: (r: Response) => void = () => {};
    lookup = () => new Promise((r) => (answer = r));
    await liftIt();
    await act(async () => button(copy.lookup_clear)?.click());
    await act(async () => answer(json([row])));
    await flush();
    expect(button(copy.lookup_clear)).toBeUndefined();
  });

  it('shows a failed lookup refresh instead of dropping it', async () => {
    await render();
    await runLookup();
    lookup = async () => json({ detail: 'x', code: 'boom' }, 500);
    await liftIt();
    expect(document.querySelector('[role="alert"]')).not.toBeNull();
  });
});
