// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, vi } from 'vitest';
import { HistoryCard } from '../components/editor/HistoryCard';
import { ReviewCard } from '../components/editor/ReviewCard';
import { ScheduleCard } from '../components/editor/ScheduleCard';
import { SeoCard } from '../components/editor/SeoCard';
import { useArticleEditor } from './useArticleEditor';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
export const FIRST = '2026-01-01T00:00:00Z';
export const SECOND = '2026-01-01T00:00:05Z';
export const STALE =
  'This article was changed somewhere else. Reload to get the latest version, then make your change again.';
export let editor: ReturnType<typeof useArticleEditor>;
let root: Root;
let host: HTMLDivElement;
export let version: string;
export let reject: string | null;
export let status: 'draft' | 'published' | 'submitted_for_review';
export let requests: { url: string; method: string; body: Record<string, unknown> }[];

export function article() {
  return {
    id: 7,
    title: 'Original',
    slug: 'original',
    category: '',
    excerpt: '',
    cover_image_url: '',
    pinned: false,
    show_in_feed: true,
    author: '',
    locale: 'en',
    translation_group: 'group',
    has_unpublished_changes: false,
    url: '/news/original',
    edit_url: '/admin/news/articles/7/body',
    meta_description: '',
    og_image: '',
    canonical_url: '',
    json_ld: null,
    rejection_note: null,
    publish_at: null,
    unpublish_at: null,
    has_published: false,
    draft_data: {},
    tags: [],
    status,
    updated_at: version,
    published_at: null,
    index_in_search: true,
  };
}
export function json(body: unknown, code = 200) {
  return new Response(JSON.stringify(body), {
    status: code,
    headers: { 'content-type': 'application/json' },
  });
}
function Harness() {
  editor = useArticleEditor(7);
  return (
    <>
      <SeoCard articleId={7} writeArticle={editor.writeArticle} />
      <ScheduleCard articleId={7} writeArticle={editor.writeArticle} />
      <HistoryCard articleId={7} writeArticle={editor.writeArticle} />
      {editor.article && (
        <ReviewCard article={editor.article} canPublish writeArticle={editor.writeArticle} />
      )}
    </>
  );
}

beforeEach(async () => {
  version = FIRST;
  reject = null;
  status = 'draft';
  requests = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      requests.push({ url, method, body });
      if (method === 'GET') {
        if (url.includes('/taxonomy/')) return json({ items: [] });
        if (url.endsWith('/revisions'))
          return json([
            {
              id: 1,
              article_id: 7,
              title: 'Restored title',
              event: 'publish',
              note: null,
              created_at: FIRST,
              created_by: 'Editor',
            },
          ]);
        return json(article());
      }
      if (reject === 'metadata' && url.endsWith('/7'))
        return json({ detail: 'Invalid title' }, 422);
      if (reject === 'tags' && url.endsWith('/tags')) return json({ detail: 'Invalid tag' }, 422);
      if (body.expected_updated_at && body.expected_updated_at !== version)
        return json({ detail: STALE, code: 'article_conflict' }, 409);
      if (url.endsWith('/tags')) return json([]);
      if (url.endsWith('/publish')) status = 'published';
      if (url.endsWith('/unpublish')) status = 'draft';
      if (url.endsWith('/submit')) status = 'submitted_for_review';
      if (url.endsWith('/approve')) status = 'published';
      if (url.endsWith('/reject')) status = 'draft';
      if (url.endsWith('/revisions/1/restore')) {
        version = SECOND;
        return json({ ...article(), title: 'Restored title' });
      }
      version = SECOND;
      return json(article());
    }),
  );
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<Harness />));
  await act(async () => {
    await editor.load();
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
export async function click(text: string) {
  const button = Array.from(document.querySelectorAll('button'))
    .filter((b) => b.textContent?.trim() === text)
    .at(-1);
  expect(button, text).toBeDefined();
  await act(async () => button?.click());
}
export async function save() {
  await act(async () => editor.patch({ title: 'Unsaved headline' }));
  await act(async () => {
    await editor.save();
  });
}
export function lastSave() {
  return requests.filter((r) => r.method === 'PUT' && r.url.endsWith('/7')).at(-1);
}

export function setVersion(next: string) {
  version = next;
}
export function setReject(next: string | null) {
  reject = next;
}
export function setStatus(next: typeof status) {
  status = next;
}
