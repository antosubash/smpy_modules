// @vitest-environment happy-dom
import type { Page } from '@inertiajs/core';
import { App, router } from '@inertiajs/react';
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { headValues } from '../page-tests/public-support';
import { PublicHead } from './PublicHead';

// The real React `Head` and core head manager, without initializing navigation (#461).
const page: Page = {
  component: 'Test',
  props: { errors: {} },
  url: '/events/',
  version: '1',
  clearHistory: false,
  encryptHistory: false,
  rescuedProps: [],
  flash: {},
  rememberedState: {},
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

const EV = headValues('Event', {
  description: 'd',
  canonical: 'https://x.example/e',
  image: 'https://x.example/i.png',
});

it('adopts the server head: one of each tag and one title after hydration', async () => {
  document.head.innerHTML = [
    '<title>Server</title>',
    '<meta name="description" data-inertia="description" content="d">',
    '<link rel="canonical" data-inertia="canonical" href="https://x.example/e">',
    '<link rel="alternate" data-inertia="hreflang-de" hreflang="de" href="https://x.example/de/e">',
    '<meta name="twitter:card" data-inertia="twitter:card" content="summary">',
    '<script type="application/ld+json" data-inertia="json-ld" nonce="n">{}</script>',
  ].join('');
  await render(
    <PublicHead
      head={EV}
      locale="en"
      alternates={[{ locale: 'de', url: 'https://x.example/de/e' }]}
      jsonLd={{ '@type': 'Event' }}
      event
    />,
  );
  expect(all('title')).toHaveLength(1);
  expect(all('title')[0]?.textContent).toBe('Event');
  expect(all('meta[name="description"]')).toHaveLength(1);
  expect(all('link[rel="canonical"]')).toHaveLength(1);
  expect(all('link[hreflang="de"]')).toHaveLength(1);
  expect(all('meta[name="twitter:card"]')).toHaveLength(1);
  expect(all('script[type="application/ld+json"]')).toHaveLength(1);
});

it('drops the event tags when the reader navigates to a listing', async () => {
  await render(<PublicHead head={EV} locale="en" event />);
  expect(all('meta[name="twitter:card"]')).toHaveLength(1);
  await render(
    <PublicHead
      head={headValues('Events', { feed_url: 'https://x.example/events/calendar.ics' })}
      locale="en"
    />,
  );
  expect(all('meta[name="twitter:card"]')).toHaveLength(0);
  expect(all('link[rel="canonical"]')).toHaveLength(0);
  expect(all('link[type="text/calendar"]')).toHaveLength(1);
});

it.each(Array.from({ length: 64 }, (_, flags) => flags))(
  'renders exactly the event tags, with the head values, for combination %i',
  async (flags) => {
    const head = headValues('Event', {
      description: flags & 1 ? 'd' : null,
      image: flags & 2 ? 'https://x.example/i.png' : null,
      robots: flags & 4 ? 'noindex,nofollow' : null,
      canonical: flags & 8 ? 'https://x.example/e' : null,
    });
    const alternates = flags & 16 ? [{ locale: 'de', url: 'https://x.example/de/e' }] : [];
    const jsonLd = flags & 32 ? { '@type': 'Event' } : null;
    await render(
      <PublicHead head={head} locale="en" alternates={alternates} jsonLd={jsonLd} event />,
    );
    const keys = ['og:title', 'og:type', 'og:locale', 'twitter:card'];
    if (head.description) keys.push('description', 'og:description');
    if (head.image) keys.push('og:image', 'twitter:image');
    if (head.robots) keys.push('robots');
    if (head.canonical) keys.push('canonical', 'og:url');
    if (alternates.length) keys.push('hreflang-de');
    if (jsonLd) keys.push('json-ld');
    expect(
      all('[data-inertia]')
        .filter((e) => e.tagName !== 'TITLE')
        .map((e) => e.getAttribute('data-inertia'))
        .sort(),
    ).toEqual(keys.sort());
    expect(all('title')).toHaveLength(1);
    const value = (selector: string) => all(selector)[0]?.getAttribute('content') ?? null;
    expect(value('meta[property="og:image"]')).toBe(head.image);
    expect(value('meta[name="robots"]')).toBe(head.robots);
    expect(value('meta[name="description"]')).toBe(head.description);
    expect(value('meta[name="twitter:card"]')).toBe(head.image ? 'summary_large_image' : 'summary');
  },
);
