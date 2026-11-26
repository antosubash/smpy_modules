import * as React from 'react';
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, vi } from 'vitest';

import { PageActions } from '../components/editor/PageActions';
import type { PageDetail } from '../utils/api';
import { AUTOSAVE_DEBOUNCE_MS } from '../utils/editorSnapshot';
import { useAutosave } from './useAutosave';
import { useEditorForm } from './useEditorForm';
import { usePageRevisions } from './usePageRevisions';
import { usePageSchedule } from './usePageSchedule';
import { usePageWorkflow } from './usePageWorkflow';

vi.mock('@inertiajs/react', () => ({ router: { reload: vi.fn(), visit: vi.fn() } }));
(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

export const FIRST = '2026-01-01T00:00:00Z';
export let server: PageDetail;
export let requests: { url: string; method: string; body: Record<string, unknown> }[];
export let form: ReturnType<typeof useEditorForm>;
export let autosave: ReturnType<typeof useAutosave>;
export let workflow: ReturnType<typeof usePageWorkflow>;
export let schedule: ReturnType<typeof usePageSchedule>;
export let revisions: ReturnType<typeof usePageRevisions>;
let hold: (() => void) | null;
let generation: number;
let host: HTMLDivElement;
let root: Root;
let loaded: PageDetail;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function Harness() {
  const [busy, setBusy] = useState(false);
  const [, setMessage] = useState<string | null>(null);
  form = useEditorForm(loaded);
  autosave = useAutosave({
    pageId: form.pageId,
    busy,
    data: form.data,
    snapshotPayload: form.snapshotPayload,
    initialSnapshot: form.snapshotPayload,
    writePayload: form.writePayload,
    writes: form.writes,
  });
  const params = { form, setBusy, setMessage, markSaved: autosave.markSaved };
  workflow = usePageWorkflow(params);
  schedule = usePageSchedule(params);
  revisions = usePageRevisions(params);
  return (
    <div>
      {form.writes?.conflict ? 'This page was changed elsewhere' : ''}
      <PageActions
        writes={form.writes}
        pageId={form.pageId}
        title={form.title}
        slug={form.effectiveSlug}
        status={form.status}
        publicPrefix="/p"
        onError={setMessage}
        onNotice={setMessage}
      />
    </div>
  );
}

beforeEach(async () => {
  vi.useFakeTimers();
  generation = 0;
  hold = null;
  requests = [];
  server = {
    id: 7,
    slug: 'original',
    locale: 'en',
    translation_group: 'group',
    title: 'Original',
    status: 'draft',
    has_published: false,
    meta_title: null,
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
    created_at: FIRST,
    updated_at: FIRST,
    json_ld: null,
    translations: [],
    draft_data: { root: { props: {} }, content: [] },
    published_data: null,
  };
  loaded = structuredClone(server);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      requests.push({ url, method, body });
      if (method === 'GET') return json(server);
      if (hold)
        await new Promise<void>((resolve) => {
          hold = resolve;
        });
      if ('expected_updated_at' in body && body.expected_updated_at !== server.updated_at) {
        return json({ detail: 'This page was changed elsewhere', code: 'page_conflict' }, 409);
      }
      generation++;
      const { expected_updated_at: _token, ...patch } = body;
      server = {
        ...server,
        ...patch,
        updated_at: `2026-01-01T00:00:${String(generation).padStart(2, '0')}Z`,
      };
      if (url.endsWith('/restore'))
        server = { ...server, title: 'Restored', draft_data: loaded.draft_data };
      return json(server);
    }),
  );
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<Harness />));
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

export async function edit(title: string) {
  await act(async () => form.setTitle(title));
}
export async function tick() {
  await act(async () => vi.advanceTimersByTimeAsync(AUTOSAVE_DEBOUNCE_MS + 1));
}
export function writes() {
  return requests.filter((r) => r.method !== 'GET');
}
export function shown() {
  return host.textContent;
}
export function pauseNextWrite() {
  hold = () => {};
}
export async function releaseWrite() {
  const release = hold;
  hold = null;
  await act(async () => release?.());
}

export async function click(text: string) {
  const button = [...host.querySelectorAll('button')].find((el) => el.textContent === text);
  if (!button) throw new Error(`Missing button ${text}`);
  await act(async () => button.click());
}

export async function unmountEditor() {
  await act(async () => root.unmount());
}
