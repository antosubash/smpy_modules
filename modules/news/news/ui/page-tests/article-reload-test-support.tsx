import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { expect, vi } from 'vitest';
import ArticleEditor from '../../pages/ArticleEditor';
import type { ArticleDetail } from '../utils/api';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

export const FIRST = '2026-01-01T00:00:00Z';
export const SECOND = '2026-01-01T00:00:05Z';
export const STALE =
  'This article was changed somewhere else. Reload to get the latest version, then make your change again.';
export const writes: { url: string; body: Record<string, unknown> }[] = [];
export let stored: ArticleDetail;
let root: Root;
let host: HTMLDivElement;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

export async function mountEditor() {
  stored = {
    id: 7,
    title: 'Original headline',
    slug: 'original',
    category: '',
    tags: [],
    excerpt: '',
    cover_image_url: '',
    pinned: false,
    show_in_feed: true,
    author: '',
    published_at: null,
    updated_at: FIRST,
    locale: 'en',
    translation_group: 'group',
    status: 'submitted_for_review',
    has_unpublished_changes: false,
    url: '/news/original',
    edit_url: '/admin/news/articles/7/body',
    draft_data: {},
    has_published: false,
    meta_description: 'Original summary',
    og_image: '/image-b.webp',
    canonical_url: '',
    index_in_search: true,
    json_ld: null,
    rejection_note: null,
    publish_at: null,
    unpublish_at: null,
  };
  writes.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (!init?.method || init.method === 'GET') {
        if (url.endsWith('/revisions'))
          return json([
            {
              id: stored.updated_at === FIRST ? 1 : 2,
              article_id: 7,
              title: stored.title,
              event: 'submit',
              note: stored.updated_at === FIRST ? 'Old history' : 'Fresh history',
              created_at: stored.updated_at,
              created_by: 'Other editor',
            },
          ]);
        if (url.includes('/taxonomy/categories'))
          return json({
            items: ['Local', 'Server category'].map((name, id) => ({
              id: id + 1,
              name,
              slug: name.toLowerCase(),
              position: id,
              article_count: 1,
              is_system: false,
            })),
          });
        if (url.includes('/taxonomy/')) return json({ items: [] });
        return json(stored);
      }
      const body = JSON.parse(String(init.body));
      writes.push({ url, body });
      if (body.expected_updated_at !== stored.updated_at)
        return json({ detail: STALE, code: 'article_conflict' }, 409);
      if (url.endsWith('/tags')) {
        stored.tags = body.tags;
        return json(body.tags);
      }
      const { expected_updated_at: _version, ...fields } = body;
      Object.assign(stored, fields);
      return json(stored);
    }),
  );
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<ArticleEditor />));
}

export async function cleanupEditor() {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
}

export function field(id: string) {
  const element = document.getElementById(id);
  if (!(element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement))
    throw new Error(`Missing field: ${id}`);
  return element;
}

export async function edit(id: string, value: string) {
  const element = field(id);
  const prototype =
    element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(prototype, 'value')?.set?.call(element, value);
    element.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

export async function click(label: string, scope: ParentNode = document) {
  const button = [...scope.querySelectorAll('button')].find(
    (button) => button.textContent?.trim() === label,
  );
  expect(button, label).toBeDefined();
  await act(async () => button?.click());
}

export async function toggle(id: string) {
  await act(async () => document.getElementById(id)?.click());
}
