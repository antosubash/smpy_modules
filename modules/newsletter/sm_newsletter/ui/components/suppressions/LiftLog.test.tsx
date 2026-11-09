// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import { PAGE_SIZE } from '../../hooks/useSuppressionList';
import type { Lift } from '../../utils/types';
import { LiftLog } from './LiftLog';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const lift = (id: number): Lift => ({
  id,
  fingerprint: `fp${id}`,
  reason: 'hard_bounce',
  list_type_key: '',
  source: 'send',
  suppressed_at: '2026-11-01T10:00:00Z',
  lifted_at: '2026-11-02T10:00:00Z',
  lifted_by: 'admin-1',
  note: `note ${id}`,
});

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('LiftLog', () => {
  let root: ReturnType<typeof createRoot>;
  let fetchMock: ReturnType<typeof vi.fn>;
  let total: number;

  beforeEach(() => {
    total = 0;
    fetchMock = vi.fn(async (url: string) => {
      const offset = Number(new URL(url, 'http://t').searchParams.get('offset') ?? 0);
      const items = Array.from({ length: Math.min(2, Math.max(0, total - offset)) }, (_, i) =>
        lift(offset + i + 1),
      );
      return json({ items, total });
    });
    vi.stubGlobal('fetch', fetchMock);
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
    [...document.querySelectorAll('button')].find((b) => b.textContent === label) as
      | HTMLButtonElement
      | undefined;
  async function render() {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () => root.render(createElement(LiftLog)));
    await flush();
  }

  it('says nothing has been lifted', async () => {
    await render();
    expect(document.body.textContent).toContain(en.suppressions.log.empty);
  });

  it('lists the lifts with who lifted them and why', async () => {
    total = 2;
    await render();
    const cells = [...document.querySelectorAll('tbody tr')].map((r) => r.textContent);
    expect(cells).toHaveLength(2);
    expect(cells[0]).toContain('fp1');
    expect(cells[0]).toContain('admin-1');
    expect(cells[0]).toContain('note 1');
    expect(button(en.campaigns.next)?.disabled).toBe(true);
  });

  it('pages by PAGE_SIZE', async () => {
    total = PAGE_SIZE + 1;
    await render();
    expect(button(en.campaigns.previous)?.disabled).toBe(true);
    await act(async () => button(en.campaigns.next)?.click());
    await flush();
    const last = String(fetchMock.mock.calls.at(-1)?.[0]);
    expect(new URL(last, 'http://t').searchParams.get('offset')).toBe(String(PAGE_SIZE));
    expect(document.body.textContent).toContain(`fp${PAGE_SIZE + 1}`);
  });
});
