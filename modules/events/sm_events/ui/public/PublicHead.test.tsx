// @vitest-environment happy-dom

import { afterEach, expect, it, vi } from 'vitest';
import { mount } from '../page-tests/test-dom';

vi.mock('@inertiajs/react', () => ({
  Head: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));
const { PublicHead } = await import('./PublicHead');

afterEach(() => {
  document.body.innerHTML = '';
});

it('writes JSON-LD that cannot break out of its script', async () => {
  const evil = '</script><script>alert(1)</script>';
  const view = await mount(
    <PublicHead title="T" locale="en" jsonLd={{ '@type': 'Event', name: evil }} />,
  );
  const scripts = view.all('script');
  expect(scripts).toHaveLength(1);
  expect(scripts[0]?.getAttribute('type')).toBe('application/ld+json');
  expect(JSON.parse(scripts[0]?.textContent ?? '').name).toBe(evil);
  expect(view.host.innerHTML).not.toContain('<script>alert');
});

it('mirrors the server head: canonical, hreflang, robots, feed', async () => {
  await mount(
    <PublicHead
      title="T"
      locale="de"
      canonical="https://x.example/events/a"
      alternates={[
        { locale: 'en', url: 'https://x.example/events/a' },
        { locale: 'x-default', url: 'https://x.example/events/a' },
      ]}
      noindex
      feedUrl="/events/calendar.ics"
    />,
  );
  expect(document.querySelector('link[rel=canonical]')?.getAttribute('href')).toBe(
    'https://x.example/events/a',
  );
  expect(
    [...document.querySelectorAll('link[rel=alternate][hreflang]')].map((l) =>
      l.getAttribute('hreflang'),
    ),
  ).toEqual(['en', 'x-default']);
  expect(document.querySelector('meta[name=robots]')?.getAttribute('content')).toBe(
    'noindex,nofollow',
  );
  expect(document.querySelector('link[type="text/calendar"]')?.getAttribute('href')).toBe(
    '/events/calendar.ics',
  );
});

it('keys every tag the server keys, so hydration replaces rather than doubles it (#461)', async () => {
  // React hoists meta and link into `document.head`, where earlier tests left theirs.
  document.head.replaceChildren();
  await mount(
    <PublicHead
      title="T"
      locale="en"
      description="d"
      canonical="https://x.example/e"
      image="https://x.example/i.png"
      alternates={[{ locale: 'de', url: 'https://x.example/de/e' }]}
      noindex
      event
      jsonLd={{ '@type': 'Event' }}
    />,
  );
  // The mocked `Head` keeps `head-key` as a plain attribute.
  const keys = [...document.querySelectorAll('[head-key]')].map((e) => e.getAttribute('head-key'));
  expect(keys.sort()).toEqual(
    [
      'canonical',
      'description',
      'hreflang-de',
      'json-ld',
      'og:description',
      'og:image',
      'og:locale',
      'og:title',
      'og:type',
      'og:url',
      'robots',
      'twitter:card',
      'twitter:image',
    ].sort(),
  );
});
