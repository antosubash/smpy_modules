// @vitest-environment happy-dom
import { router } from '@inertiajs/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { click, mount } from './test-dom';
import { collection, flush, stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
// WebGL does not exist here: the canvas is the e2e's to prove.
vi.mock('../components/map/MapCanvas', () => ({
  default: ({
    source,
    styleUrl,
    onSelect,
  }: {
    source: { kind: string };
    styleUrl?: string;
    onSelect: (id: string) => void;
  }) => (
    <button
      type="button"
      data-testid="fake-map"
      data-kind={source.kind}
      data-style={styleUrl}
      onClick={() => onSelect('i9')}
    />
  ),
}));

const Collection = (await import('../pages/Collection')).default;

const rights = {
  can_edit: false,
  can_manage: false,
  can_share: false,
  can_publish: false,
  direct_upload_threshold: 1024,
};

afterEach(() => vi.unstubAllGlobals());

describe('Collection map tab', () => {
  it('reads the admin routes and sends a click on a point to the image viewer', async () => {
    const calls = stubFetch({
      'GET /api/images/collections/c1/images': { items: [], next_cursor: null, total: 0 },
      'HEAD /api/images/collections/c1/map.pmtiles': null,
      // past one page of points: the archive is read
      'GET /api/images/collections/c1/points': { features: [], next_cursor: 'more' },
    });
    const view = await mount(
      <Collection
        collection={collection({ located_count: 1 })}
        {...rights}
        map_style_url="https://tiles.example.org/s"
      />,
    );
    await flush();
    await click(view.find('[data-testid="images-tab-map"]') as HTMLElement);
    await flush(10);
    expect(
      calls.some((c) => c.method === 'HEAD' && c.url === '/api/images/collections/c1/map.pmtiles'),
    ).toBe(true);
    const map = view.find('[data-testid="fake-map"]');
    expect(map?.getAttribute('data-kind')).toBe('tiles');
    expect(map?.getAttribute('data-style')).toBe('https://tiles.example.org/s');
    await click(map as HTMLElement);
    expect(router.visit).toHaveBeenCalledWith('/admin/images/images/i9');
    await view.unmount();
  });
});
