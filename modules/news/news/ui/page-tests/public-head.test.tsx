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
        "<title>Canopy &amp; soil</title><meta head-key="description" name="description" content="A &lt;forest&gt; story"/><meta head-key="og:description" property="og:description" content="A &lt;forest&gt; story"/><meta head-key="og:title" property="og:title" content="Canopy &amp; soil"/><meta head-key="og:type" property="og:type" content="article"/><meta head-key="og:url" property="og:url" content="https://example.test/news/canopy"/><meta head-key="og:site_name" property="og:site_name" content="Field Notes"/><meta head-key="article:published_time" property="article:published_time" content="2026-11-24T00:00:00Z"/><meta head-key="article:author" property="article:author" content="Ada"/><meta head-key="article:section" property="article:section" content="Trees"/><meta head-key="og:image" property="og:image" content="https://example.test/cover.jpg"/><meta head-key="twitter:image" name="twitter:image" content="https://example.test/cover.jpg"/><meta head-key="twitter:card" name="twitter:card" content="summary_large_image"/><meta head-key="twitter:site" name="twitter:site" content="@field"/><link head-key="canonical" rel="canonical" href="https://example.test/news/canopy"/><meta head-key="robots" name="robots" content="noindex,nofollow"/><script head-key="json-ld" type="application/ld+json">{"@type":"NewsArticle","headline":"\\u003c/script>\\u003c!--\\u003cSCRIPT>"}</script>",
      ]
    `);
  });
  it('omits optional tags and defaults to an indexable summary card', () => {
    renderToStaticMarkup(
      <Article title="Plain" data={{ content: [] }} meta_description={null} og_image={null} />,
    );
    expect(heads).toMatchInlineSnapshot(`
      [
        "<title>Plain</title><meta head-key="og:title" property="og:title" content="Plain"/><meta head-key="og:type" property="og:type" content="article"/><meta head-key="twitter:card" name="twitter:card" content="summary"/>",
      ]
    `);
  });
  it('uses the exact server head prop rather than rebuilding it from display props', () => {
    const head = {
      title: 'Server title',
      description: 'Server description',
      canonical: 'https://example.test/de/news/',
      locale: 'de',
      feed_url: 'https://example.test/de/news/feed.xml',
      alternates: [{ locale: 'en', url: 'https://example.test/news/' }],
    };
    renderToStaticMarkup(<Archive {...archive} head={head} query="different title" />);
    renderToStaticMarkup(<Article {...article} head={head} />);
    expect(heads).toHaveLength(2);
    for (const markup of heads) {
      expect(markup).toContain('<title>Server title</title>');
      expect(markup).toContain(
        'head-key="canonical" rel="canonical" href="https://example.test/de/news/"',
      );
      expect(markup).toContain('head-key="og:locale" property="og:locale" content="de"');
      expect(markup).toContain('head-key="hreflang-en"');
      expect(markup).toContain('head-key="feed"');
    }
  });
  it('preserves the archive title and search robots tag', () => {
    renderToStaticMarkup(<Archive {...archive} query="trees & soil" />);
    expect(heads).toMatchInlineSnapshot(`
      [
        "<title>trees &amp; soil — News</title><meta head-key="robots" name="robots" content="noindex,follow"/>",
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
