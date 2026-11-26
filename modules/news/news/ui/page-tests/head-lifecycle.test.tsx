// @vitest-environment happy-dom
import { App, router } from '@inertiajs/react';
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ArchiveHead } from '../components/ArchiveHead';
import { ArticleHead } from '../components/ArticleHead';
import type { PublicHeadValues } from '../components/PublicHead';
import {
  archiveHead,
  archiveServerHead,
  article,
  articleHead,
  articleServerHead,
  page,
} from './head-test-support';

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
  ])
    expect(all(`[data-inertia="${key}"]`), key).toHaveLength(1);
  expect(JSON.parse(document.head.querySelector('script')?.textContent ?? '')).toEqual(
    article.json_ld,
  );
});

function assertCurrent(head: PublicHeadValues, kind: string) {
  expect(all('title')).toHaveLength(1);
  expect(document.title).toBe(head.title);
  expect(all('link[rel="canonical"]')).toHaveLength(1);
  expect(all('link[rel="canonical"]')[0].getAttribute('href')).toBe(head.canonical);
  expect(all('meta[property="og:url"]')).toHaveLength(1);
  expect(all('meta[property="og:url"]')[0].getAttribute('content')).toBe(head.canonical);
  expect(all('meta[property="og:type"]')[0].getAttribute('content')).toBe(kind);
  expect(all('meta[property="og:locale"]')[0].getAttribute('content')).toBe(head.locale);
  expect(
    all('link[hreflang]')
      .map((el) => [el.getAttribute('hreflang'), el.getAttribute('href')])
      .sort(),
  ).toEqual((head.alternates ?? []).map((a) => [a.locale, a.url]).sort());
  expect(all('link[type="application/rss+xml"]')).toHaveLength(1);
  expect(all('link[type="application/rss+xml"]')[0].getAttribute('title')).toBe(head.title);
  expect(all('link[type="application/rss+xml"]')[0].getAttribute('href')).toBe(head.feed_url);
  const expected: Record<string, string | null | undefined> = {
    description: head.description,
    'og:description': head.description,
    'og:title': head.title,
    'og:type': kind,
    'og:url': head.canonical,
    'og:site_name': head.site_name,
    'og:locale': head.locale,
    robots: head.robots,
  };
  if (kind === 'article') {
    Object.assign(expected, {
      'og:image': head.image,
      'twitter:image': head.image,
      'twitter:site': head.twitter_handle,
      'twitter:card': head.image ? 'summary_large_image' : 'summary',
      'article:published_time': head.published_at,
      'article:author': head.author,
      'article:section': head.section,
      robots: head.index_in_search === false ? 'noindex,nofollow' : head.robots,
    });
  }
  expect(
    all('meta')
      .filter((el) => el.getAttribute('property') !== 'og:locale:alternate')
      .map((el) => [
        el.getAttribute('property') ?? el.getAttribute('name'),
        el.getAttribute('content'),
      ])
      .sort(),
  ).toEqual(
    Object.entries(expected)
      .filter(([, value]) => value)
      .sort(),
  );
  expect(
    all('meta[property="og:locale:alternate"]')
      .map((el) => el.getAttribute('content'))
      .sort(),
  ).toEqual(
    (head.alternates ?? [])
      .filter((a) => a.locale !== head.locale && a.locale !== 'x-default')
      .map((a) => a.locale)
      .sort(),
  );
  const scripts = all('script[type="application/ld+json"]');
  expect(scripts).toHaveLength(head.json_ld ? 1 : 0);
  if (head.json_ld) {
    expect(JSON.parse(scripts[0].textContent ?? '')).toEqual(head.json_ld);
  }
  const keys = all('[data-inertia]').map((el) => el.getAttribute('data-inertia'));
  expect(new Set(keys).size).toBe(keys.length);
}

it('hydrates the complete archive, visits an article, then returns to the archive (#462)', async () => {
  document.head.innerHTML = archiveServerHead;
  const before = all('meta, link')
    .map((el) => el.outerHTML)
    .sort();
  await render(<ArchiveHead heading="Archive" head={archiveHead} />);
  assertCurrent(archiveHead, 'website');
  expect(
    all('meta, link')
      .map((el) => el.outerHTML)
      .sort(),
  ).toEqual(before);
  await render(<ArticleHead {...article} head={articleHead} />);
  assertCurrent({ ...archiveHead, ...articleHead }, 'article');
  expect(all('meta[name="robots"]')[0].getAttribute('content')).toBe('noindex,nofollow');
  await render(<ArchiveHead heading="Archive" head={archiveHead} />);
  assertCurrent(archiveHead, 'website');
  expect(
    all(
      'meta[property^="article:"], meta[name^="twitter:"], meta[property="og:image"], script[type="application/ld+json"], meta[name="robots"]',
    ),
  ).toHaveLength(0);
});

it('replaces page-one metadata and removes hreflang on a searched page two', async () => {
  document.head.innerHTML = archiveServerHead;
  await render(<ArchiveHead heading="Archive" head={archiveHead} />);
  const pageTwo = { ...archiveHead, canonical: 'https://example.test/news/?page=2' };
  await render(<ArchiveHead heading="Archive" head={pageTwo} />);
  assertCurrent(pageTwo, 'website');
  const next = {
    ...archiveHead,
    title: 'Trees',
    canonical: 'https://example.test/de/news/?q=trees&page=2',
    locale: 'de',
    feed_url: 'https://example.test/de/news/feed.xml',
    alternates: [],
    robots: 'noindex,follow',
  };
  await render(<ArchiveHead heading="Archive" head={next} />);
  assertCurrent(next, 'website');
  expect(all('meta[property="og:locale:alternate"]')).toHaveLength(0);
  expect(all('meta[name="robots"]')[0].getAttribute('content')).toBe('noindex,follow');
});

it('hydrates an article and replaces all optional tags on article-to-article visits', async () => {
  document.head.innerHTML = articleServerHead;
  const before = all('meta, link')
    .map((el) => el.outerHTML)
    .sort();
  await render(<ArticleHead {...article} head={articleHead} />);
  expect(
    all('meta, link')
      .map((el) => el.outerHTML)
      .sort(),
  ).toEqual(before);
  expect(JSON.parse(document.head.querySelector('script')?.textContent ?? '')).toEqual(
    article.json_ld,
  );
  assertCurrent({ ...archiveHead, ...articleHead }, 'article');
  const next = {
    ...articleHead,
    title: 'Zweite',
    canonical: 'https://example.test/de/news/zweite',
    description: null,
    image: null,
    author: null,
    section: null,
    published_at: null,
    twitter_handle: null,
    index_in_search: true,
    json_ld: null,
    locale: 'de',
    alternates: [],
    feed_url: 'https://example.test/de/news/feed.xml',
  };
  await render(<ArticleHead {...article} head={next} />);
  assertCurrent({ ...archiveHead, ...next }, 'article');
  expect(
    all(
      'link[hreflang], meta[property="og:locale:alternate"], meta[property^="article:"], meta[property="og:image"], meta[name="twitter:image"], meta[name="twitter:site"], meta[name="robots"], meta[name="description"], meta[property="og:description"], script[type="application/ld+json"]',
    ),
  ).toHaveLength(0);
  expect(all('meta[name="twitter:card"]')[0].getAttribute('content')).toBe('summary');
  await render(<ArchiveHead heading="Archive" head={archiveHead} />);
  assertCurrent(archiveHead, 'website');
});
