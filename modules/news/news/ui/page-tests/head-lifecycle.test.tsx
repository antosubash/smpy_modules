// @vitest-environment happy-dom
import type { Page } from '@inertiajs/core';
import { App, router } from '@inertiajs/react';
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ArchiveHead } from '../components/ArchiveHead';
import { ArticleHead, type ArticleHeadProps } from '../components/ArticleHead';

// Exercise the real React Head and core DOM renderer, without initializing navigation.
const page: Page = {
  component: 'Test',
  props: { errors: {} },
  url: '/news/',
  version: '1',
  clearHistory: false,
  encryptHistory: false,
  rescuedProps: [],
  flash: {},
  rememberedState: {},
};
const article: ArticleHeadProps = {
  title: 'Story',
  meta_description: 'Description',
  og_image: 'https://example.test/image.png',
  canonical_url: 'https://example.test/news/story',
  og_url: 'https://example.test/news/story',
  site_name: 'Site',
  twitter_handle: '@site',
  author: 'Ada',
  category: 'Trees',
  published_at: '2026-01-01T12:00:00Z',
  index_in_search: false,
  json_ld: { '@type': 'NewsArticle', headline: '</script><!--' },
};
const Empty = () => null;
let root: Root;

beforeEach(() => {
  vi.spyOn(router, 'init').mockImplementation(() => {});
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  await new Promise((resolve) => setTimeout(resolve, 10));
  document.head.replaceChildren();
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

async function render(head: ReactNode) {
  await act(async () => {
    root.render(
      <App initialPage={page} initialComponent={Empty}>
        {() => head}
      </App>,
    );
  });
  await new Promise((resolve) => setTimeout(resolve, 10));
}

const all = (selector: string) => [...document.head.querySelectorAll(selector)];

it('renders every article tag without server injection, including former fragment children', async () => {
  await render(<ArticleHead {...article} />);
  for (const key of [
    'description',
    'og:description',
    'og:title',
    'og:type',
    'og:url',
    'og:site_name',
    'og:image',
    'article:published_time',
    'article:author',
    'article:section',
    'twitter:card',
    'twitter:image',
    'twitter:site',
    'canonical',
    'robots',
    'json-ld',
  ]) {
    expect(all(`[data-inertia="${key}"]`), key).toHaveLength(1);
  }
  expect(JSON.parse(document.head.querySelector('script')?.textContent ?? '')).toEqual(
    article.json_ld,
  );
});

it('adopts keyed server article tags and retains unkeyed locale and alternate tags', async () => {
  document.head.innerHTML = [
    '<title>Story</title>',
    '<link rel="canonical" data-inertia="canonical" href="https://example.test/news/story">',
    '<meta property="og:title" data-inertia="og:title" content="Story">',
    '<meta property="og:locale" content="en">',
    '<link rel="alternate" hreflang="de" href="/de/news/story">',
  ].join('');
  await render(<ArticleHead {...article} />);
  expect(all('title')).toHaveLength(1);
  expect(all('link[rel="canonical"]')).toHaveLength(1);
  expect(all('meta[property="og:title"]')).toHaveLength(1);
  expect(all('meta[property="og:locale"]')).toHaveLength(1);
  expect(all('link[hreflang="de"]')).toHaveLength(1);
});

it('adopts archive robots, but preserves the pre-existing unkeyed archive metadata on navigation', async () => {
  document.head.innerHTML = [
    '<title>Archive</title>',
    '<link rel="canonical" href="https://example.test/news/">',
    '<meta property="og:title" content="Archive">',
    '<meta property="og:type" content="website">',
    '<meta name="robots" data-inertia="robots" content="noindex,follow">',
    '<link rel="alternate" type="application/rss+xml" href="/news/feed.xml">',
  ].join('');
  await render(<ArchiveHead heading="Archive" query="trees" />);
  expect(all('title')).toHaveLength(1);
  expect(all('meta[name="robots"]')).toHaveLength(1);
  expect(all('link[rel="canonical"]')).toHaveLength(1);
  await render(<ArticleHead {...article} />);
  expect(all('link[rel="canonical"]')).toHaveLength(2);
  expect(all('meta[property="og:type"]').map((tag) => tag.getAttribute('content'))).toEqual([
    'website',
    'article',
  ]);
  await render(<ArchiveHead heading="Archive" />);
  expect(all('link[rel="canonical"]')).toHaveLength(1);
  expect(all('meta[property="og:type"]').map((tag) => tag.getAttribute('content'))).toEqual([
    'website',
  ]);
  expect(all('meta[name="robots"]')).toHaveLength(0);
});

it('removes managed article metadata when navigating to an archive from an article load', async () => {
  await render(<ArticleHead {...article} />);
  await render(<ArchiveHead heading="Archive" />);
  expect(all('link[rel="canonical"]')).toHaveLength(0);
  expect(all('meta[property="og:type"]')).toHaveLength(0);
});
