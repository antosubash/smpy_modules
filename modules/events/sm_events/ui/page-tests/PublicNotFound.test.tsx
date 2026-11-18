// @vitest-environment happy-dom

import { afterEach, expect, it, vi } from 'vitest';
import { item } from './public-support';
import { mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { default: PublicNotFound } = await import('../../pages/PublicNotFound');

afterEach(() => {
  document.body.innerHTML = '';
});

it('shows suggestions and an index link', async () => {
  const view = await mount(
    <PublicNotFound
      locale="en"
      index_url="/events/"
      suggestions={[
        item({ key: 'a', title: 'Concert' }),
        item({ key: 'b', title: 'Talk', url: '/events/talk' }),
      ]}
    />,
  );
  expect(view.find('h1')?.textContent).toBe('Page not found');
  expect(view.find('a[href="/events/"]')?.textContent).toBe('See all events');
  expect(view.all('li a').map((a) => a.textContent)).toEqual(['Concert', 'Talk']);
});

it('has no suggestions section when there are none', async () => {
  const view = await mount(<PublicNotFound locale="de" index_url="/de/events/" suggestions={[]} />);
  expect(view.find('ul')).toBeNull();
  expect(view.find('a[href="/de/events/"]')).not.toBeNull();
});
