// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { toast } from 'sonner';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ArticleEditor from '../../pages/ArticleEditor';
import NewsList from '../../pages/NewsList';
import Trash from '../../pages/Trash';

vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  Link: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  router: { visit: vi.fn() },
  usePage: () => ({
    props: {
      article_id: 7,
      preview_url: '/preview',
      auth: {
        permissions: ['news.view', 'news.edit', 'news.publish'],
      },
    },
  }),
}));
(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLDivElement;
let root: Root;
let calls: { url: string; method: string }[];
let trashed: boolean;
let staleAction: boolean;
let missing: boolean;
const article = {
  id: 7,
  title: 'Subject',
  slug: 'subject',
  category: '',
  tags: [],
  locale: 'en',
  excerpt: '',
  cover_image_url: '',
  pinned: false,
  show_in_feed: true,
  author: '',
  translation_group: 'group',
  has_unpublished_changes: false,
  meta_description: '',
  og_image: '',
  canonical_url: '',
  json_ld: null,
  rejection_note: null,
  publish_at: null,
  unpublish_at: null,
  has_published: true,
  draft_data: {},
  status: 'published',
  published_at: null,
  updated_at: '2026-01-01T00:00:00Z',
  index_in_search: true,
  url: '/news/subject',
  edit_url: '/admin/news/articles/7/body',
};
function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}
async function click(label: string) {
  const button = Array.from(document.querySelectorAll('button'))
    .filter((b) => b.textContent?.trim() === label)
    .at(-1);
  expect(button, label).toBeDefined();
  await act(async () => button?.click());
}
beforeEach(() => {
  calls = [];
  trashed = false;
  staleAction = false;
  missing = false;
  vi.spyOn(toast, 'success');
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET';
      calls.push({ url, method });
      if (method !== 'GET') {
        if (staleAction) {
          missing = true;
          return json({ detail: 'Article not found.' }, 404);
        }
        if (url.endsWith('/trash')) trashed = true;
        return new Response(null, { status: 204 });
      }
      if (url.includes('/revisions')) return json([]);
      if (url.includes('/categories') || url.includes('/taxonomy/')) return json({ items: [] });
      if (url.includes('/detail')) return json(article);
      const bin = url.includes('trashed=true');
      const items = !missing && trashed === bin ? [article] : [];
      return json({ items, total: items.length });
    }),
  );
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it.each([
  { screen: 'list', Page: NewsList, trigger: 'Move to trash' },
  { screen: 'editor', Page: ArticleEditor, trigger: 'Move article to trash' },
])('$screen removal uses recoverable trash even for publishers', async ({ Page, trigger }) => {
  await act(async () => root.render(<Page />));
  await click(trigger);
  const dialog = document.querySelector('[role="alertdialog"]');
  expect(dialog?.textContent).toContain('Restore it from Trash');
  expect(dialog?.textContent).not.toContain('cannot be undone');
  await click('Move to trash');
  expect(calls.filter((c) => c.method !== 'GET')).toEqual([
    { url: '/api/news/articles/7/trash', method: 'POST' },
  ]);
  expect(toast.success).toHaveBeenCalledWith('Article moved to Trash. You can restore it there.');
});

it('Trash keeps the permanent purge wording and endpoint', async () => {
  trashed = true;
  await act(async () => root.render(<Trash />));
  await click('Delete for good');
  expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain('cannot be undone');
  await click('Delete for good');
  expect(calls.filter((c) => c.method !== 'GET')).toEqual([
    { url: '/api/news/articles/7/purge', method: 'DELETE' },
  ]);
});

it.each(['Restore', 'Delete for good'])(
  'Trash refetches after stale %s answers 404',
  async (action) => {
    trashed = true;
    staleAction = true;
    vi.spyOn(toast, 'error');
    await act(async () => root.render(<Trash />));
    expect(document.querySelector('[data-testid="trashed-row"]')).not.toBeNull();
    await click(action);
    if (action === 'Delete for good') await click(action);
    expect(document.querySelector('[data-testid="trashed-row"]')).toBeNull();
    expect(toast.error).toHaveBeenCalledWith('Article not found.');
  },
);
