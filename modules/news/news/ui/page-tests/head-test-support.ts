import type { Page } from '@inertiajs/core';
import type { ArticleHeadProps } from '../components/ArticleHead';

// Exercise the real React Head and core DOM renderer, without initializing navigation.
export const page: Page = {
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
export const article: ArticleHeadProps = {
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
export const archiveHead = {
  title: 'Archive — Site',
  description: 'All stories',
  canonical: 'https://example.test/news/',
  site_name: 'Site',
  locale: 'en',
  feed_url: 'https://example.test/news/feed.xml',
  alternates: [
    { locale: 'en', url: 'https://example.test/news/' },
    { locale: 'de', url: 'https://example.test/de/news/' },
    { locale: 'x-default', url: 'https://example.test/news/' },
  ],
};
export const articleHead = {
  title: article.title,
  description: article.meta_description,
  canonical: article.canonical_url,
  image: article.og_image,
  site_name: article.site_name,
  twitter_handle: article.twitter_handle,
  author: article.author,
  section: article.category,
  published_at: article.published_at,
  index_in_search: false,
  json_ld: article.json_ld,
  locale: 'en',
  feed_url: archiveHead.feed_url,
  alternates: [
    { locale: 'en', url: 'https://example.test/news/story' },
    { locale: 'de', url: 'https://example.test/de/news/geschichte' },
  ],
};
// Independent server markup: catching an unkeyed tag requires starting with it present.
export const archiveServerHead = `<title>Archive — Site</title>
    <link rel="canonical" data-inertia="canonical" href="https://example.test/news/">
    <meta name="description" data-inertia="description" content="All stories">
    <meta property="og:title" data-inertia="og:title" content="Archive — Site">
    <meta property="og:description" data-inertia="og:description" content="All stories">
    <meta property="og:type" data-inertia="og:type" content="website">
    <meta property="og:url" data-inertia="og:url" content="https://example.test/news/">
    <meta property="og:site_name" data-inertia="og:site_name" content="Site">
    <meta property="og:locale" data-inertia="og:locale" content="en">
    <meta property="og:locale:alternate" data-inertia="og:locale:alternate-de" content="de">
    <link rel="alternate" data-inertia="hreflang-en" hreflang="en" href="https://example.test/news/">
    <link rel="alternate" data-inertia="hreflang-de" hreflang="de" href="https://example.test/de/news/">
    <link rel="alternate" data-inertia="hreflang-x-default" hreflang="x-default" href="https://example.test/news/">
    <link rel="alternate" data-inertia="feed" type="application/rss+xml" title="Archive — Site" href="https://example.test/news/feed.xml">`;
export const articleServerHead = String.raw`<title>Story</title>
    <link rel="canonical" data-inertia="canonical" href="https://example.test/news/story">
    <meta name="description" data-inertia="description" content="Description">
    <meta property="og:title" data-inertia="og:title" content="Story">
    <meta property="og:description" data-inertia="og:description" content="Description">
    <meta property="og:type" data-inertia="og:type" content="article">
    <meta property="og:url" data-inertia="og:url" content="https://example.test/news/story">
    <meta property="og:site_name" data-inertia="og:site_name" content="Site">
    <meta property="og:image" data-inertia="og:image" content="https://example.test/image.png">
    <meta property="article:author" data-inertia="article:author" content="Ada">
    <meta property="article:section" data-inertia="article:section" content="Trees">
    <meta property="article:published_time" data-inertia="article:published_time" content="2026-01-01T12:00:00Z">
    <meta name="twitter:card" data-inertia="twitter:card" content="summary_large_image">
    <meta name="twitter:image" data-inertia="twitter:image" content="https://example.test/image.png">
    <meta name="twitter:site" data-inertia="twitter:site" content="@site">
    <meta name="robots" data-inertia="robots" content="noindex,nofollow">
    <meta property="og:locale" data-inertia="og:locale" content="en">
    <meta property="og:locale:alternate" data-inertia="og:locale:alternate-de" content="de">
    <link rel="alternate" data-inertia="hreflang-en" hreflang="en" href="https://example.test/news/story">
    <link rel="alternate" data-inertia="hreflang-de" hreflang="de" href="https://example.test/de/news/geschichte">
    <link rel="alternate" data-inertia="feed" type="application/rss+xml" title="Story" href="https://example.test/news/feed.xml">
    <script type="application/ld+json" data-inertia="json-ld">{"@type":"NewsArticle","headline":"<\/script><\u0021--"}</script>`;
