// @vitest-environment happy-dom
import type * as React from 'react';
import { act } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  cleanupEditor,
  click,
  edit,
  field,
  mountEditor,
  SECOND,
  STALE,
  stored,
  toggle,
  writes,
} from './article-reload-test-support';

vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  Link: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  router: { visit: vi.fn() },
  usePage: () => ({
    props: {
      article_id: 7,
      preview_url: '/preview',
      auth: { permissions: ['news.view', 'news.edit', 'news.publish'] },
    },
  }),
}));

beforeEach(mountEditor);
afterEach(cleanupEditor);
afterEach(() => vi.useRealTimers());

it.each(['Save search settings', 'Save'])(
  'Reload after a conflict on %s discards the whole screen and saves only fresh edits',
  async (trigger) => {
    await edit('article-title', 'Rejected headline');
    await edit('article-slug', 'rejected-slug');
    await edit('article-author', 'Rejected author');
    await edit('article-date', '2026-03-01');
    await edit('article-time', '09:30');
    const category = document.getElementById('article-category') as HTMLSelectElement;
    await act(async () => {
      category.value = 'Local';
      category.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await edit('news-article-tags', 'Rejected tag,');
    await edit('news-article-tags', 'Uncommitted tag text');
    await toggle('article-pinned');
    await toggle('article-show-in-feed');
    await edit('article-meta-description', 'Rejected summary');
    await edit('article-og-image', '/image-a.webp');
    await edit('article-canonical-url', 'https://example.com/rejected');
    await toggle('article-index-in-search');
    await edit('article-publish-at', '2026-04-01T08:30');
    await edit('article-unpublish-at', '2026-04-02T08:30');

    // Another editor has saved every field since this screen loaded.
    Object.assign(stored, {
      updated_at: SECOND,
      title: 'Server headline',
      slug: 'server-slug',
      category: 'Server category',
      tags: ['Server tag'],
      author: 'Server author',
      published_at: '2026-02-02T12:45:00Z',
      meta_description: 'Server summary',
      og_image: '/image-b.webp',
      canonical_url: 'https://example.com/server',
      // These match the original, and differ from the unsaved values.
      pinned: false,
      show_in_feed: true,
      index_in_search: true,
      publish_at: null,
      unpublish_at: null,
      status: 'draft',
    });
    await click(trigger);
    expect(document.body.textContent).toContain(STALE);
    expect(field('article-og-image').value).toBe('/image-a.webp');
    expect(field('article-title').value).toBe('Rejected headline');

    await click('Reload');
    expect(field('article-title').value).toBe('Server headline');
    expect(field('article-og-image').value).toBe('/image-b.webp');
    expect(field('article-meta-description').value).toBe('Server summary');
    expect(field('article-slug').value).toBe('server-slug');
    expect(field('article-author').value).toBe('Server author');
    expect(field('article-date').value).toBe('2026-02-02');
    expect(field('article-time').value).toBe('12:45');
    expect((document.getElementById('article-category') as HTMLSelectElement).value).toBe(
      'Server category',
    );
    expect(document.querySelector('[data-testid="article-tag"]')?.textContent).toContain(
      'Server tag',
    );
    expect(document.body.textContent).not.toContain('Rejected tag');
    expect(field('news-article-tags').value).toBe('');
    expect(document.getElementById('article-pinned')?.getAttribute('data-state')).toBe('unchecked');
    expect(document.getElementById('article-show-in-feed')?.getAttribute('data-state')).toBe(
      'checked',
    );
    expect(field('article-canonical-url').value).toBe('https://example.com/server');
    expect(document.getElementById('article-index-in-search')?.getAttribute('data-state')).toBe(
      'checked',
    );
    expect(field('article-publish-at').value).toBe('');
    expect(field('article-unpublish-at').value).toBe('');
    expect(document.body.textContent).toContain('Submit for review');
    expect(document.body.textContent).toContain('Fresh history');
    expect(document.body.textContent).not.toContain('Old history');
    expect(document.body.textContent).not.toContain(STALE);

    writes.length = 0;
    await edit('article-meta-description', 'Summary after Reload');
    await click('Save search settings');
    await edit('article-title', 'Headline after Reload');
    await click('Save');
    await click('Save schedule');
    expect(writes).toEqual([
      {
        url: '/api/news/articles/7',
        body: {
          expected_updated_at: SECOND,
          meta_description: 'Summary after Reload',
          og_image: '/image-b.webp',
          canonical_url: 'https://example.com/server',
          index_in_search: true,
        },
      },
      {
        url: '/api/news/articles/7',
        body: {
          expected_updated_at: SECOND,
          title: 'Headline after Reload',
          slug: 'server-slug',
          category: 'Server category',
          author: 'Server author',
          published_at: '2026-02-02T12:45:00Z',
          pinned: false,
          show_in_feed: true,
        },
      },
      {
        url: '/api/news/articles/7/tags',
        body: { tags: ['Server tag'], expected_updated_at: SECOND },
      },
      {
        url: '/api/news/articles/7/schedule',
        body: { publish_at: null, unpublish_at: null, expected_updated_at: SECOND },
      },
    ]);
    expect(stored.title).toBe('Headline after Reload');
    expect(stored.meta_description).toBe('Summary after Reload');
    expect(stored.og_image).toBe('/image-b.webp');
    expect(document.body.textContent).not.toContain(STALE);
  },
);

it('Reload discards the rejected review note and closes its dialog', async () => {
  vi.useFakeTimers();
  await click('Send back');
  const note = document.querySelector('textarea[aria-label="Reason"]') as HTMLTextAreaElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set?.call(
      note,
      'Rejected review note',
    );
    note.dispatchEvent(new Event('input', { bubbles: true }));
  });
  stored.updated_at = SECOND;
  const dialog = document.querySelector('[role="dialog"]');
  if (!dialog) throw new Error('Missing review dialog');
  await click('Send back', dialog);
  expect(document.body.textContent).toContain(STALE);
  await act(async () => vi.advanceTimersByTimeAsync(800));
  await click('Cancel');
  await click('Reload');
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  await click('Send back');
  expect(
    (document.querySelector('textarea[aria-label="Reason"]') as HTMLTextAreaElement).value,
  ).toBe('');
});
