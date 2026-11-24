import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const heads = vi.hoisted(() => [] as string[]);
vi.mock('@inertiajs/react', () => ({
  Head: ({ title, children }: { title: string; children: React.ReactNode }) => {
    heads.push(
      renderToStaticMarkup(
        <>
          <title>{title}</title>
          {children}
        </>,
      ),
    );
    return null;
  },
  usePage: () => ({ props: {} }),
}));
vi.mock('@simple-module-py/ui/components/BrandingHead', () => ({ BrandingHead: () => null }));
vi.mock('@puckeditor/core', () => ({ Render: () => null }));
(globalThis as { React?: unknown }).React = React;

const { default: PublicArticle } = await import('../../pages/PublicArticle');
const { default: PublicIndex } = await import('../../pages/PublicIndex');
const publicExports = await import('@simple-module-py/news');

const article = {
  title: 'Canopy & soil',
  data: { content: [] },
  meta_description: 'A <forest> story',
  og_image: 'https://example.test/cover.jpg',
  canonical_url: 'https://example.test/news/canopy',
  og_url: 'https://example.test/news/canopy',
  index_in_search: false,
  json_ld: { '@type': 'NewsArticle', headline: '</script><!--<SCRIPT>' },
  site_name: 'Field Notes',
  twitter_handle: '@field',
  published_at: '2026-11-24T00:00:00Z',
  author: 'Ada',
  category: 'Trees',
};
const archive = {
  heading: 'News',
  items: [],
  page: 1,
  pages: 1,
  total: 0,
  base_path: '/news/',
  feed_url: '/news/feed.xml',
};

beforeEach(() => {
  heads.length = 0;
});

describe.each(['page', 'package export'])('public head output via %s (#446)', (source) => {
  const Article = source === 'page' ? PublicArticle : publicExports.ArticleHead;
  const Archive = source === 'page' ? PublicIndex : publicExports.ArchiveHead;
  it('preserves the complete article head, including escaped JSON-LD', () => {
    renderToStaticMarkup(<Article {...article} />);
    expect(heads).toMatchInlineSnapshot(`
      [
        "<title>Canopy &amp; soil</title><meta name="description" content="A &lt;forest&gt; story"/><meta property="og:description" content="A &lt;forest&gt; story"/><meta property="og:title" content="Canopy &amp; soil"/><meta property="og:type" content="article"/><meta property="og:url" content="https://example.test/news/canopy"/><meta property="og:site_name" content="Field Notes"/><meta property="article:published_time" content="2026-11-24T00:00:00Z"/><meta property="article:author" content="Ada"/><meta property="article:section" content="Trees"/><meta property="og:image" content="https://example.test/cover.jpg"/><meta name="twitter:image" content="https://example.test/cover.jpg"/><meta name="twitter:card" content="summary_large_image"/><meta name="twitter:site" content="@field"/><link rel="canonical" href="https://example.test/news/canopy"/><meta name="robots" content="noindex,nofollow"/><script type="application/ld+json">{"@type":"NewsArticle","headline":"\\u003c/script>\\u003c!--\\u003cSCRIPT>"}</script>",
      ]
    `);
  });
  it('omits optional tags and defaults to an indexable summary card', () => {
    renderToStaticMarkup(
      <Article title="Plain" data={{ content: [] }} meta_description={null} og_image={null} />,
    );
    expect(heads).toMatchInlineSnapshot(`
      [
        "<title>Plain</title><meta property="og:title" content="Plain"/><meta property="og:type" content="article"/><meta name="twitter:card" content="summary"/>",
      ]
    `);
  });
  it('preserves the archive title and search robots tag', () => {
    renderToStaticMarkup(<Archive {...archive} query="trees & soil" />);
    expect(heads).toMatchInlineSnapshot(`
      [
        "<title>trees &amp; soil — News</title><meta name="robots" content="noindex,follow"/>",
      ]
    `);
  });
  it('leaves an unfiltered archive indexable', () => {
    renderToStaticMarkup(<Archive {...archive} />);
    expect(heads).toMatchInlineSnapshot(`
      [
        "<title>News</title>",
      ]
    `);
  });
});

it('exports JSON-LD escaping without losing the original JSON values', () => {
  const doc = { headline: '</script><!--<SCRIPT>' };
  const safe = publicExports.safeJsonLd(doc);
  expect(safe).not.toContain('<');
  expect(JSON.parse(safe)).toEqual(doc);
});
