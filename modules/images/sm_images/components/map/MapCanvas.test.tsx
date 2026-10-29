// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { flush } from '../../page-tests/support';
import { mount } from '../../test-dom';

type Handler = (event?: unknown) => void;
const handlers: Record<string, Handler> = {};
let drawn = 0;

vi.mock('maplibre-gl', () => ({
  addProtocol: vi.fn(),
  setWorkerUrl: vi.fn(),
  NavigationControl: class {},
  Map: class {
    on(name: string, ...rest: unknown[]) {
      // `on(type, listener)` and `on(type, layer, listener)`
      handlers[name] = rest[rest.length - 1] as Handler;
    }
    addControl() {}
    addSource() {}
    addLayer() {}
    getLayer() {
      return {};
    }
    queryRenderedFeatures() {
      return Array.from({ length: drawn });
    }
    getCanvas() {
      return { style: { setProperty() {}, removeProperty() {} } };
    }
    fitBounds() {}
    remove() {}
  },
}));
vi.mock('maplibre-gl/dist/maplibre-gl.css', () => ({}));
vi.mock('pmtiles', () => ({
  Protocol: class {
    tile = vi.fn();
  },
}));
vi.mock('./mapWorker', () => ({ installMapWorker: vi.fn() }));

const MapCanvas = (await import('./MapCanvas')).default;
const source = { kind: 'points', features: [] } as never;

describe('MapCanvas', () => {
  it('says so when the map reports an error', async () => {
    const view = await mount(
      <MapCanvas source={source} bbox={null} label="m" onSelect={() => {}} />,
    );
    await flush();
    expect(view.find('[data-testid="images-map-error"]')).toBeNull();
    handlers.error?.();
    await flush();
    expect(view.find('[data-testid="images-map-error"]')?.textContent).toBe(
      'The map could not be loaded.',
    );
    await view.unmount();
  });

  it('reports how many features are drawn once the map is idle', async () => {
    drawn = 3;
    const view = await mount(
      <MapCanvas source={source} bbox={null} label="m" onSelect={() => {}} />,
    );
    await flush();
    handlers.idle?.();
    expect(view.find('[data-testid="images-map"]')?.getAttribute('data-map-features')).toBe('3');
    await view.unmount();
  });
});
