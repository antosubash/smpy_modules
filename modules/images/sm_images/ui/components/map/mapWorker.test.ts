// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

const setWorkerUrl = vi.fn();
vi.mock('maplibre-gl', () => ({ setWorkerUrl }));

afterEach(() => vi.unstubAllGlobals());

describe('installMapWorker', () => {
  it('hands MapLibre a same-origin blob: URL, never a cross-origin script URL', async () => {
    const blobs: Blob[] = [];
    URL.createObjectURL = (blob: Blob | MediaSource) => {
      blobs.push(blob as Blob);
      return 'blob:http://localhost/worker-1';
    };
    const { installMapWorker } = await import('./mapWorker');
    installMapWorker();
    installMapWorker(); // idempotent: one blob however often a map mounts
    expect(setWorkerUrl).toHaveBeenCalledTimes(1);
    expect(setWorkerUrl).toHaveBeenCalledWith('blob:http://localhost/worker-1');
    // The blob is the real worker, not a stub: it carries MapLibre's licence header.
    expect(await blobs[0]?.text()).toContain('MapLibre GL JS');
  });
});
