// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { collection, flush, stubFetch } from './support';
import { click, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());

const Collections = (await import('../../pages/Collections')).default;

const first = {
  items: [collection(), collection({ id: 'c2', name: 'Rocks' })],
  next_cursor: null,
  total: 2,
};

afterEach(() => vi.unstubAllGlobals());

describe('Collections', () => {
  it('lists the first page the server rendered, each card linking to its collection', async () => {
    const calls = stubFetch({});
    const view = await mount(
      <Collections collections={first} can_create={false} can_publish={false} />,
    );
    const cards = view.all<HTMLAnchorElement>('[data-testid="images-collection-card"]');
    expect(cards.map((c) => c.getAttribute('href'))).toEqual([
      '/admin/images/c1',
      '/admin/images/c2',
    ]);
    expect(view.host.textContent).toContain('2 images');
    expect(calls).toHaveLength(0);
    await view.unmount();
  });

  it('offers "New collection" only to a caller who may create', async () => {
    stubFetch({});
    const no = await mount(
      <Collections collections={first} can_create={false} can_publish={false} />,
    );
    expect(no.find('[data-testid="images-new-collection"]')).toBeNull();
    await no.unmount();
    const yes = await mount(
      <Collections collections={first} can_create={true} can_publish={false} />,
    );
    expect(yes.find('[data-testid="images-new-collection"]')).not.toBeNull();
    await yes.unmount();
  });

  it('asks the API for the chosen filter and shows what comes back', async () => {
    const calls = stubFetch({
      'GET /api/images/collections': {
        items: [collection({ id: 'c3', name: 'Shared one' })],
        next_cursor: null,
        total: 1,
      },
    });
    const view = await mount(
      <Collections collections={first} can_create={false} can_publish={false} />,
    );
    await click(view.find('[data-testid="images-collection-filter-shared"]'));
    await flush();
    expect(calls.at(-1)?.url).toBe('/api/images/collections?filter=shared');
    expect(view.all('[data-testid="images-collection-card"]')).toHaveLength(1);
    expect(view.host.textContent).toContain('Shared one');
    await view.unmount();
  });
});
