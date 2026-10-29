// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { flush } from '../../page-tests/support';
import { mount } from '../../test-dom';

type Handler = (event?: unknown) => void;
const handlers: Record<string, Handler> = {};
let drawn = 0;
let options: { style?: unknown } = {};
const setStyle = vi.fn();
const addLayer = vi.fn();
const fitBounds = vi.fn();
const controls: unknown[] = [];

vi.mock('maplibre-gl', () => ({
  addProtocol: vi.fn(),
  setWorkerUrl: vi.fn(),
  NavigationControl: class {},
  AttributionControl: class {
    constructor(public options: unknown) {}
  },
  Map: class {
    constructor(opts: { style?: unknown }) {
      options = opts;
    }
    on(name: string, ...rest: unknown[]) {
      // `on(type, listener)` and `on(type, layer, listener)`
      handlers[name] = rest[rest.length - 1] as Handler;
    }
    addControl(control: unknown) {
      controls.push(control);
    }
    addSource() {}
    addLayer(layer: unknown, beforeId?: string) {
      addLayer(layer, beforeId);
    }
    setStyle(style: unknown, opts: unknown) {
      setStyle(style, opts);
    }
    getLayer() {
      return {};
    }
    queryRenderedFeatures() {
      return Array.from({ length: drawn });
    }
    getCanvas() {
      return { style: { setProperty() {}, removeProperty() {} } };
    }
    fitBounds(...args: unknown[]) {
      fitBounds(...args);
    }
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

const errorShown = (view: { find: (s: string) => HTMLElement | null }) =>
  view.find('[data-testid="images-map-error"]') !== null;

describe('MapCanvas', () => {
  it('fits the points it draws, clear of the zoom control, not the page-load box', async () => {
    // QA TEST-003: the box came from the page props, read before the upload's
    // other points were located; and a marker sat under the top-right control.
    const at = (x: number, y: number) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [x, y] },
      properties: { id: `${x}`, captured_at: null, group_id: null },
    });
    const points = { kind: 'points', features: [at(14, 60), at(-8, 53), at(25, 65)] } as never;
    fitBounds.mockClear();
    const view = await mount(
      <MapCanvas source={points} bbox={[14, 59, 15, 60]} label="m" onSelect={() => {}} />,
    );
    await flush();
    handlers.load?.();
    const [bounds, opts] = fitBounds.mock.calls[0] as [
      unknown,
      { padding: Record<string, number> },
    ];
    expect(bounds).toEqual([
      [-8, 53],
      [25, 65],
    ]);
    expect(opts.padding.right).toBeGreaterThanOrEqual(56);
    expect(opts.padding.top).toBeGreaterThanOrEqual(48);
    await view.unmount();
  });

  it('only logs an error after the map loaded (a failed tile is not a failed map)', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const view = await mount(
      <MapCanvas source={source} bbox={null} label="m" onSelect={() => {}} />,
    );
    await flush();
    handlers.load?.();
    handlers.error?.({ error: new Error('tile 404') });
    await flush();
    expect(errorShown(view)).toBe(false);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
    await view.unmount();
  });

  it('clears an early error once the map loads after all', async () => {
    const view = await mount(
      <MapCanvas source={source} bbox={null} label="m" onSelect={() => {}} />,
    );
    await flush();
    handlers.error?.({ error: new Error('style blip') });
    await flush();
    expect(errorShown(view)).toBe(true);
    handlers.load?.();
    await flush();
    expect(errorShown(view)).toBe(false);
    await view.unmount();
  });

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

  describe('basemap', () => {
    const STYLE_URL = 'https://tiles.example.org/styles/positron';
    const mountWith = (styleUrl?: string) =>
      mount(
        <MapCanvas source={source} styleUrl={styleUrl} bbox={null} label="m" onSelect={() => {}} />,
      );

    it('draws the configured style, with a compact attribution', async () => {
      controls.length = 0;
      const view = await mountWith(STYLE_URL);
      await flush();
      expect(options.style).toBe(STYLE_URL);
      expect(controls).toContainEqual(expect.objectContaining({ options: { compact: true } }));
      await view.unmount();
    });

    it('draws the flat background when no style is configured', async () => {
      const view = await mountWith('');
      await flush();
      expect(options.style).toEqual(expect.objectContaining({ version: 8, sources: {} }));
      await view.unmount();
    });

    it('falls back to the flat background when the style cannot be fetched, and still draws the points', async () => {
      setStyle.mockClear();
      addLayer.mockClear();
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const view = await mountWith(STYLE_URL);
      await flush();
      handlers.error?.({ error: new Error('Failed to fetch') });
      await flush();
      expect(setStyle).toHaveBeenCalledWith(expect.objectContaining({ version: 8, sources: {} }), {
        diff: false,
      });
      expect(errorShown(view)).toBe(false);
      handlers.load?.();
      await flush();
      expect(addLayer).toHaveBeenCalledTimes(2);
      expect(view.find('[data-testid="images-map"]')?.getAttribute('data-map-ready')).toBe(
        'points',
      );
      warn.mockRestore();
      await view.unmount();
    });

    it('does not give up the basemap for a tile that failed before the first load', async () => {
      setStyle.mockClear();
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const view = await mountWith(STYLE_URL);
      await flush();
      handlers.styledata?.();
      handlers.error?.({ error: new Error('tile 404'), sourceId: 'openmaptiles', tile: {} });
      await flush();
      expect(setStyle).not.toHaveBeenCalled();
      expect(errorShown(view)).toBe(false);
      warn.mockRestore();
      await view.unmount();
    });

    it('adds the points above every basemap layer once the style loaded', async () => {
      addLayer.mockClear();
      const view = await mountWith(STYLE_URL);
      await flush();
      expect(addLayer).not.toHaveBeenCalled();
      handlers.styledata?.();
      handlers.load?.();
      await flush();
      expect(
        addLayer.mock.calls.map(([layer, before]) => [(layer as { id: string }).id, before]),
      ).toEqual([
        ['images-clusters', undefined],
        ['images-points', undefined],
      ]);
      await view.unmount();
    });
  });
});
