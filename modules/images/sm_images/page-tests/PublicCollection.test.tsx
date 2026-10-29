// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { click, mount } from '../test-dom';
import { flush, stubFetch } from './support';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
// WebGL does not exist here: the canvas is the e2e's to prove.
vi.mock('../components/map/MapCanvas', () => ({
  default: ({ source, onSelect }: { source: { kind: string }; onSelect: (id: string) => void }) => (
    <button type="button" data-testid="fake-map" data-kind={source.kind} onClick={() => onSelect('i2')} />
  ),
}));
vi.mock('@simple-module-py/ui/components/BrandingHead', () => ({ BrandingHead: () => null }));

const PublicCollection = (await import('../pages/PublicCollection')).default;

const info = {
  slug: 'trees',
  name: 'Trees',
  description: 'Old ones',
  image_count: 2,
  located_count: 1,
  bbox: [1, 2, 1, 2],
};
const tile = (id: string) => ({
  id,
  width: 8,
  height: 8,
  thumb_url: `/api/images/public/c/trees/images/${id}/r/small?v=1.x`,
  display_url: `/api/images/public/c/trees/images/${id}/display?v=1.x`,
});
const LIST = 'GET /api/images/public/c/trees/images';
const POINTS = 'GET /api/images/public/c/trees/points';
const MAP = 'HEAD /api/images/public/c/trees/map.pmtiles';
const point = { type: 'Feature', geometry: { type: 'Point', coordinates: [1, 2] }, properties: { id: 'i2' } };

afterEach(() => vi.unstubAllGlobals());

describe('PublicCollection', () => {
  it('shows public thumbnails only, and opens the display copy in a lightbox', async () => {
    const calls = stubFetch({
      [LIST]: { items: [tile('i1'), tile('i2')], next_cursor: null },
      [MAP]: null,
      [POINTS]: { features: [point], next_cursor: null },
    });
    const view = await mount(<PublicCollection collection={{ ...info, located_count: 0 }} />);
    await flush();
    const srcs = view.all<HTMLImageElement>('[data-testid="images-public-tile"] img').map((i) => i.getAttribute('src'));
    expect(srcs).toEqual([tile('i1').thumb_url, tile('i2').thumb_url]);
    expect(calls.every((c) => c.url.startsWith('/api/images/public/'))).toBe(true);
    expect(view.find('[data-testid="images-map"], [data-testid="fake-map"]')).toBeNull();

    await click(view.all('[data-testid="images-public-tile"]')[0] as HTMLElement);
    expect(view.find('[data-testid="images-lightbox-image"]')?.getAttribute('src')).toBe(tile('i1').display_url);
    await click(view.find('[data-testid="images-lightbox"]') as HTMLElement);
    expect(view.find('[data-testid="images-lightbox"]')).toBeNull();
    await view.unmount();
  });

  it('draws the map for a located collection and opens the clicked point', async () => {
    stubFetch({
      [LIST]: { items: [tile('i1'), tile('i2')], next_cursor: null },
      [MAP]: { ok: true },
      [POINTS]: { features: [point], next_cursor: null },
    });
    const view = await mount(<PublicCollection collection={info} />);
    await flush();
    await flush();
    const map = view.find('[data-testid="fake-map"]');
    expect(map?.getAttribute('data-kind')).toBe('tiles');
    await click(map as HTMLElement);
    expect(view.find('[data-testid="images-lightbox-image"]')?.getAttribute('src')).toBe(tile('i2').display_url);
    await view.unmount();
  });

  it('says so when the gallery cannot be read', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('x', { status: 500 })));
    const view = await mount(<PublicCollection collection={{ ...info, located_count: 0 }} />);
    await flush();
    expect(view.find('[role="alert"]')?.textContent).toContain('could not be loaded');
    await view.unmount();
  });
});
