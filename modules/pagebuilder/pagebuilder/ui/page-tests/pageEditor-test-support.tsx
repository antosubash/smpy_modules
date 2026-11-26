import type { Data } from '@puckeditor/core';
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, vi } from 'vitest';

import PageEditor from '../../pages/PageEditor';
import { getPage, type PageDetail } from '../utils/api';
import { AUTOSAVE_DEBOUNCE_MS } from '../utils/editorSnapshot';

const inertia = vi.hoisted(() => ({ visit: vi.fn(), reload: vi.fn() }));
let props: { page: PageDetail; revisions: []; locales: string[] };
vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  router: inertia,
  usePage: () => ({ props }),
}));
vi.mock('@simple-module-py/ui/components/BrandingHead', () => ({ BrandingHead: () => null }));
// Puck owns its internal canvas state. Remounting it on Reload must replace
// that state too, not just the toolbar and inspector's controlled inputs.
vi.mock('@puckeditor/core', () => ({
  Puck: ({ data }: { data: Data }) => {
    const [canvas] = React.useState(data);
    return <output data-testid="canvas">{JSON.stringify(canvas)}</output>;
  },
}));

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
export let host: HTMLDivElement;
let root: Root;
export let server: PageDetail;
let generation: number;
export let writes: Record<string, unknown>[];

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

beforeEach(async () => {
  vi.useFakeTimers();
  generation = 0;
  writes = [];
  server = {
    id: 7,
    slug: 'original',
    locale: 'en',
    translation_group: 'group',
    title: 'Original',
    status: 'draft',
    has_published: false,
    meta_title: 'Original SEO',
    meta_description: null,
    og_image: null,
    canonical_url: null,
    index_in_search: true,
    rejection_note: null,
    publish_at: null,
    unpublish_at: null,
    parent_id: null,
    is_template: false,
    show_in_header_nav: false,
    show_in_footer: false,
    deleted_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: null,
    json_ld: null,
    translations: [],
    draft_data: { root: { props: {} }, content: [] },
    published_data: null,
  };
  props = { page: structuredClone(server), revisions: [], locales: ['en'] };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (!init?.method) return json(url.includes('?') ? { items: [] } : server);
      const body = JSON.parse(String(init.body));
      writes.push(body);
      if ('expected_updated_at' in body && body.expected_updated_at !== server.updated_at) {
        return json({ detail: 'Changed', code: 'page_conflict' }, 409);
      }
      const { expected_updated_at: _token, ...patch } = body;
      server = { ...server, ...patch, updated_at: '2026-01-01T00:00:10Z' };
      return json(server);
    }),
  );
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  // This is the Inertia boundary: preserveState:false gives the page a new
  // mount. Preserving state deliberately keeps its old form and canvas here.
  inertia.visit.mockImplementation(async (_url, options) => {
    props = { ...props, page: await getPage(server.id) };
    if (options?.preserveState === false) generation++;
    root.render(<PageEditor key={generation} />);
  });
  await act(async () => root.render(<PageEditor key={generation} />));
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

export async function click(text: string) {
  const button = [...host.querySelectorAll('button')].find((el) => el.textContent === text);
  expect(button, text).toBeDefined();
  await act(async () => button?.click());
}
export async function edit(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
export function title() {
  const input = host.querySelector<HTMLInputElement>('input[placeholder="Page title"]');
  if (!input) throw new Error('Missing title input');
  return input;
}
export async function tick() {
  await act(async () => vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS + 1));
}
export function externalEdit() {
  server = {
    ...server,
    title: 'Server title',
    meta_title: 'Server SEO',
    slug: 'server-slug',
    updated_at: '2026-01-01T00:00:05Z',
    show_in_header_nav: true,
    draft_data: { root: { props: { title: 'Server canvas' } }, content: [] },
  };
}

export function visitMock() {
  return inertia.visit;
}
export function failNextWrite(status: number, code?: string) {
  vi.mocked(fetch).mockImplementationOnce(async () => json({ detail: 'Refused', code }, status));
}
