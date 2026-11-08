// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import Import from '../../../pages/Import';
import type { ImportJob } from '../../utils/importTypes';
import { stagedJob } from './fixture';

const page = vi.hoisted(() => ({ props: {} as Record<string, unknown> }));
vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  usePage: () => ({ props: page.props }),
}));
vi.mock('@simple-module-py/ui/components/PageShell', () => ({
  PageShell: ({ children }: { children: unknown }) => createElement('div', null, children as never),
}));
vi.mock('@simple-module-py/ui/layouts/AuthenticatedLayout', () => ({
  AuthenticatedLayout: () => null,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const wait = () => act(async () => void (await new Promise((r) => setTimeout(r, 20))));

describe('Import screen against a stale state', () => {
  let root: ReturnType<typeof createRoot>;
  let calls: string[];
  let current: ImportJob;
  let refuse: { method: string; status: number; code: string } | null;

  beforeEach(() => {
    calls = [];
    refuse = null;
    page.props = { lists: ['news'], initial_import: 7 };
    current = stagedJob();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET';
        const path = String(url).replace('/api/newsletter', '');
        calls.push(`${method} ${path}`);
        if (path === '/imports' && method === 'GET') return json([]);
        if (path === '/imports' && method === 'POST') return json(current);
        if (refuse && refuse.method === method) {
          return json({ detail: 'x', code: refuse.code }, refuse.status);
        }
        return json(current);
      }),
    );
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  async function render() {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () => root.render(createElement(Import)));
    await wait();
  }
  const button = (name: string) =>
    [...document.querySelectorAll('button')].find((b) => b.textContent === name);
  const text = () => document.body.textContent ?? '';

  it('sends the status it shows with a discard, and reloads on a 409', async () => {
    await render();
    refuse = { method: 'DELETE', status: 409, code: 'import_not_staged' };
    await act(async () => button(en.import.discard)?.click());
    current = stagedJob({ status: 'done', processed: 12, created: 12 });
    await act(async () => button(en.import.discard_confirm.confirm)?.click());
    await wait();
    expect(calls).toContain('DELETE /imports/7?status=staged');
    expect(calls.filter((c) => c === 'GET /imports/7')).toHaveLength(2);
    expect(text()).toContain(en.import.done);
    expect(button(en.import.discard)).toBeUndefined();
    expect(text()).toContain(en.errors.import_not_staged);
  });

  it('returns to the start on a 404, keeping the message', async () => {
    await render();
    refuse = { method: 'POST', status: 404, code: 'not_found' };
    await act(async () => button(en.import.apply)?.click());
    await wait();
    expect(text()).toContain(en.import.upload_label);
    expect(button(en.import.apply)).toBeUndefined();
    expect(text()).toContain(en.errors.not_found);
  });

  it('reloads the import when applying is refused with a 409', async () => {
    await render();
    refuse = { method: 'PATCH', status: 409, code: 'import_not_staged' };
    current = stagedJob({ status: 'running', total: 12, processed: 3 });
    await act(async () => button(en.import.apply)?.click());
    await wait();
    expect(text()).toContain('3 of 12 rows processed');
  });

  it('disables Start for an import with no rows and says why', async () => {
    current = stagedJob({ total: 0, files: [{ name: 'a.csv', kind: 'subscribed', rows: 0 }] });
    await render();
    expect((button(en.import.apply) as HTMLButtonElement).disabled).toBe(true);
    expect(text()).toContain(en.import.no_rows);
  });

  it('uploads once when Upload is clicked five times in one tick', async () => {
    page.props = { lists: ['news'], initial_import: null };
    await render();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['a'], 'subscribed.csv', { type: 'text/csv' });
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    // The page lists no list: the first one is preselected.
    await act(async () => {
      for (let i = 0; i < 5; i++) button(en.import.upload)?.click();
    });
    await wait();
    expect(calls.filter((c) => c === 'POST /imports')).toHaveLength(1);
  });

  it('returns focus to "New list" when the dialog is closed with Escape', async () => {
    page.props = { lists: ['news'], initial_import: null };
    await render();
    const trigger = button(en.import.new_list) as HTMLButtonElement;
    trigger.focus();
    await act(async () => trigger.click());
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    await act(async () => {
      document.activeElement?.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
      );
    });
    await wait();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});
