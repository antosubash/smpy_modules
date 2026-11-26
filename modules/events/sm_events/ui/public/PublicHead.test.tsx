// @vitest-environment happy-dom

import { afterEach, expect, it, vi } from 'vitest';
import { headValues } from '../page-tests/public-support';
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
    <PublicHead head={headValues('T')} locale="en" jsonLd={{ '@type': 'Event', name: evil }} />,
  );
  const scripts = view.all('script');
  expect(scripts).toHaveLength(1);
  expect(scripts[0]?.getAttribute('type')).toBe('application/ld+json');
  expect(JSON.parse(scripts[0]?.textContent ?? '').name).toBe(evil);
  expect(view.host.innerHTML).not.toContain('<script>alert');
});

it('renders the server head values verbatim: canonical, hreflang, robots, feed', async () => {
  document.head.replaceChildren();
  await mount(
    <PublicHead
      head={headValues('T', {
        canonical: 'https://x.example/events/a',
        robots: 'noindex,follow',
        feed_url: 'https://x.example/events/calendar.ics',
      })}
      locale="de"
      alternates={[
        { locale: 'en', url: 'https://x.example/events/a' },
        { locale: 'x-default', url: 'https://x.example/events/a' },
      ]}
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
    'noindex,follow',
  );
  expect(document.querySelector('link[type="text/calendar"]')?.getAttribute('href')).toBe(
    'https://x.example/events/calendar.ics',
  );
});
