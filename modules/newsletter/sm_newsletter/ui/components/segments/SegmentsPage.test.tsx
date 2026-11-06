// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../../../locales/en.json';
import Segments from '../../../pages/Segments';
import { COUNT_DEBOUNCE_MS } from '../../hooks/useAudienceCount';

const page = vi.hoisted(() => ({ props: { can_edit: true } as Record<string, unknown> }));
vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  usePage: () => ({ props: page.props }),
}));
vi.mock('@simple-module-py/ui/components/PageShell', () => ({
  PageShell: ({ children, actions }: { children: unknown; actions: unknown }) =>
    createElement('div', null, actions as never, children as never),
}));
vi.mock('@simple-module-py/ui/layouts/AuthenticatedLayout', () => ({
  AuthenticatedLayout: () => null,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const fields = [
  {
    key: 'city',
    label: 'City',
    type: 'text',
    many: false,
    choices: [],
    system: false,
    ops: ['is'],
  },
];

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('Segments page', () => {
  let root: ReturnType<typeof createRoot>;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    page.props = { can_edit: true };
    fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('/lists')) return json(['news', 'events']);
      if (url.endsWith('/fields')) return json(fields);
      if (url.endsWith('/segments/preview')) return json({ count: 3 });
      return json([]);
    });
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => {
    act(() => root.unmount());
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  const wait = (ms: number) =>
    act(async () => {
      await new Promise((r) => setTimeout(r, ms));
    });
  const previews = () =>
    fetchMock.mock.calls.filter(([u]) => String(u).endsWith('/segments/preview'));
  const newButton = () =>
    [...document.querySelectorAll('button')].find((b) => b.textContent === en.segments.new);
  async function render() {
    root = createRoot(document.body.appendChild(document.createElement('div')));
    await act(async () => root.render(createElement(Segments)));
    await wait(COUNT_DEBOUNCE_MS + 100);
  }

  it('asks for no preview on load or on a list switch', async () => {
    await render();
    expect(previews()).toHaveLength(0);
    const list = document.getElementById('newsletter-segments-list') as HTMLSelectElement;
    await act(async () => {
      list.value = 'events';
      list.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await wait(COUNT_DEBOUNCE_MS + 100);
    expect(previews()).toHaveLength(0);
  });

  it('asks once the editor opens', async () => {
    await render();
    await act(async () => newButton()?.click());
    await wait(COUNT_DEBOUNCE_MS + 100);
    expect(previews()).toHaveLength(1);
  });

  it('never mounts the editor for a viewer', async () => {
    page.props = { can_edit: false };
    await render();
    expect(newButton()).toBeUndefined();
    expect(previews()).toHaveLength(0);
  });
});
