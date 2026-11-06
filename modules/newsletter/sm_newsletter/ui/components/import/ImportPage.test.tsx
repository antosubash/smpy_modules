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

describe('Import page', () => {
  let root: ReturnType<typeof createRoot>;
  let calls: { method: string; path: string; body: unknown }[];
  let current: ImportJob;

  beforeEach(() => {
    calls = [];
    page.props = { lists: ['news', 'events'], initial_import: 7 };
    current = stagedJob();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET';
        const path = String(url).replace('/api/newsletter', '');
        calls.push({
          method,
          path,
          body: typeof init?.body === 'string' ? JSON.parse(init.body) : (init?.body ?? null),
        });
        if (path === '/imports' && method === 'GET') {
          return json([
            {
              id: 7,
              list_type_key: 'news',
              status: current.status,
              total: 12,
              processed: 0,
              created_at: '2026-11-05T10:00:00Z',
            },
          ]);
        }
        if (method === 'POST' && path.endsWith('/apply')) {
          current = { ...current, status: 'queued' };
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
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
  }
  const button = (name: string) =>
    [...document.querySelectorAll('button')].find((b) => b.textContent === name);
  const text = () => document.body.textContent ?? '';

  it('shows the summary, the mapping and the tags of a staged import', async () => {
    await render();
    expect(text()).toContain('subscribed.csv');
    expect(text()).toContain(en.import.kinds.subscribed);
    expect(text()).toContain(en.import.suppression_note);
    expect(document.querySelector('select[aria-label="Email Address"]')).not.toBeNull();
    expect(text()).toContain('VIP');
    expect(text()).toContain(en.import.tags_hint_segments);
  });

  it('saves the mapping, then applies', async () => {
    await render();
    calls.length = 0;
    await act(async () => button(en.import.apply)?.click());
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    const writes = calls.filter((c) => c.method !== 'GET');
    expect(writes.map((c) => `${c.method} ${c.path}`)).toEqual([
      'PATCH /imports/7',
      'POST /imports/7/apply',
    ]);
    expect(writes[0].body).toEqual({ mapping: { fields: { '0': 'email' }, tags: false } });
    expect(text()).toContain(en.import.status.queued);
  });

  it('does not apply when saving the mapping fails', async () => {
    const original = globalThis.fetch;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) =>
        init?.method === 'PATCH'
          ? json({ detail: 'x', code: 'import_bad_mapping' }, 422)
          : original(url, init),
      ),
    );
    await render();
    await act(async () => button(en.import.apply)?.click());
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(calls.some((c) => c.path.endsWith('/apply'))).toBe(false);
    expect(text()).toContain(en.errors.import_bad_mapping);
  });

  it('asks before discarding', async () => {
    await render();
    await act(async () => button(en.import.discard)?.click());
    expect(text()).toContain(en.import.discard_confirm.title);
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
    await act(async () => button(en.import.discard_confirm.confirm)?.click());
    expect(calls.some((c) => c.method === 'DELETE' && c.path === '/imports/7')).toBe(true);
    expect(text()).toContain(en.import.upload_label);
  });

  it('shows the progress of a running import', async () => {
    current = stagedJob({ status: 'running', total: 12, processed: 5 });
    await render();
    expect(text()).toContain('5 of 12 rows processed');
    expect(button(en.import.apply)).toBeUndefined();
  });

  it('shows the counts, the errors and the download link of a finished import', async () => {
    current = stagedJob({
      status: 'done',
      processed: 12,
      created: 8,
      failed: 2,
      errors_total: 2,
      errors: [{ file: 0, line: 4, code: 'invalid_email', field: 'email' }],
    });
    await render();
    expect(text()).toContain(en.import.done);
    expect(text()).toContain(en.import.counts.created);
    expect(text()).toContain('subscribed.csv');
    expect(text()).toContain(en.import.row_errors.invalid_email);
    const link = [...document.querySelectorAll('a')].find(
      (a) => a.textContent === en.import.errors_download,
    );
    expect(link?.getAttribute('href')).toBe('/api/newsletter/imports/7/errors.csv');
  });

  it('shows why a failed import failed and offers to apply again', async () => {
    current = stagedJob({ status: 'failed', error_code: 'import_failed' });
    await render();
    expect(text()).toContain(en.errors.import_failed);
    await act(async () => button(en.import.apply_again)?.click());
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(calls.some((c) => c.method === 'POST' && c.path === '/imports/7/apply')).toBe(true);
  });

  it('uploads the chosen files to the chosen list', async () => {
    page.props = { lists: ['news', 'events'], initial_import: null };
    await render();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.accept).toBe('.zip,.csv');
    expect(input.multiple).toBe(true);
    expect((button(en.import.upload) as HTMLButtonElement).disabled).toBe(true);
    const file = new File(['a'], 'subscribed.csv', { type: 'text/csv' });
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await act(async () => button(en.import.upload)?.click());
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    const post = calls.find((c) => c.method === 'POST' && c.path === '/imports');
    const form = post?.body as FormData;
    expect(form.get('list')).toBe('news');
    expect(form.getAll('files')).toHaveLength(1);
    expect(text()).toContain('subscribed.csv');
  });
});
