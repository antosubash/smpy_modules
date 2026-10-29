import { setWorkerUrl } from 'maplibre-gl';
// The worker's source, inlined: it has no imports of its own.
import workerSource from 'maplibre-gl/dist/maplibre-gl-worker.mjs?raw';

let installed = false;

/**
 * Point MapLibre at its worker through a `blob:` URL.
 *
 * MapLibre looks for the worker next to its own module, which is not where a
 * bundler puts it. Naming the file by URL works in the production bundle (same
 * origin) but not under `make dev`: the page is on the API port and the file on
 * Vite's, and the CSP's `worker-src 'self' blob:` refuses a cross-origin worker
 * ("Worker failed to load"). A blob is allowed by that CSP in both modes, so
 * the same code runs in both and no CSP source has to be added.
 */
export function installMapWorker(): void {
  if (installed) return;
  const blob = new Blob([workerSource], { type: 'text/javascript' });
  setWorkerUrl(URL.createObjectURL(blob));
  installed = true;
}
