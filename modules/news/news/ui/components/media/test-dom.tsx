import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { vi } from 'vitest';
import type { ArticleWrite } from '../../hooks/useArticleEditor';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
export const writes: Record<string, unknown>[] = [];
export const requests: string[] = [];

export function fakeApi() {
  writes.length = 0;
  requests.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      requests.push(url);
      if (init?.body) writes.push(JSON.parse(String(init.body)));
      const body = url.startsWith('/api/pagebuilder/uploads')
        ? {
            items: [
              {
                id: 1,
                filename: 'cover.webp',
                original_filename: 'Cover photo',
                content_type: 'image/webp',
                size_bytes: 2048,
                url: '/media/default/cover.webp',
                width: 800,
                height: 600,
                folder: '',
                alt_text: 'A green canopy',
                caption: '',
                credit: '',
                variants: {},
                created_at: null,
              },
            ],
            total: 1,
            next_cursor: null,
            folders: [],
          }
        : {
            id: 7,
            title: 'Story',
            slug: 'story',
            locale: 'en',
            category: '',
            tags: [],
            author: '',
            status: 'draft',
            published_at: null,
            created_at: null,
            updated_at: null,
            pinned: false,
            show_in_feed: true,
            url: '/news/story',
            edit_url: '/admin/news/articles/7/body',
            draft_data: {},
            has_published: false,
            meta_description: '',
            og_image: '',
            canonical_url: '',
            index_in_search: true,
            json_ld: null,
            rejection_note: null,
            publish_at: null,
            unpublish_at: null,
          };
      return new Response(JSON.stringify(body), {
        headers: { 'Content-Type': 'application/json' },
      });
    }),
  );
}
export async function mount(node: ReactNode) {
  const host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(node));
  await flush();
}
export async function flush() {
  for (let i = 0; i < 4; i++)
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 25));
    });
}
export function cleanup() {
  act(() => root?.unmount());
  document.body.replaceChildren();
  vi.unstubAllGlobals();
}
export const button = (text: string) =>
  [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === text);
export async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
export async function pickCover() {
  const browse = button('Choose from media library');
  if (!browse) throw new Error('Missing media picker button');
  await act(async () => browse.click());
  await flush();
  const pick = [...document.querySelectorAll<HTMLButtonElement>('[role="dialog"] ul button')].find(
    (b) => b.textContent?.includes('Cover photo'),
  );
  if (!pick) throw new Error('Missing cover in gallery');
  await act(async () => pick.click());
  await flush();
}

export function input(selector = 'input'): HTMLInputElement {
  const found = document.querySelector<HTMLInputElement>(selector);
  if (!found) throw new Error(`Missing input: ${selector}`);
  return found;
}

/** The editor's write queue reduced to a pass-through: these tests are about the picker. */
export const directWrite: ArticleWrite = async (action) => {
  await action(null);
  return true;
};
