// @vitest-environment happy-dom
import type { Page } from '@inertiajs/core';
import { App, router } from '@inertiajs/react';
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
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
      title="Event"
      locale="en"
      description="d"
      canonical="https://x.example/e"
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
  await render(<PublicHead title="Event" locale="en" canonical="https://x.example/e" event />);
  expect(all('meta[name="twitter:card"]')).toHaveLength(1);
  await render(<PublicHead title="Events" locale="en" feedUrl="/events/calendar.ics" />);
  expect(all('meta[name="twitter:card"]')).toHaveLength(0);
  expect(all('link[rel="canonical"]')).toHaveLength(0);
  expect(all('link[type="text/calendar"]')).toHaveLength(1);
});
