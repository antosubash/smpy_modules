/** Shared stand-ins for the page tests: a routed `fetch` and fixture rows. */

import { vi } from 'vitest';
import type { Collection, ImageItem, ImportJob } from '../utils/types';
import { act } from './test-dom';

export type Call = { url: string; method: string; body: unknown };
type Handler = (call: Call) => unknown;

/** Install a `fetch` that answers by `"METHOD path-without-query"`; every call
 *  is recorded. An unrouted request fails the test loudly. */
export function stubFetch(routes: Record<string, Handler | unknown>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? 'GET').toUpperCase();
      const raw = typeof init?.body === 'string' ? init.body : null;
      const call = { url, method, body: raw ? JSON.parse(raw) : (init?.body ?? null) };
      calls.push(call);
      const route = routes[`${method} ${url.split('?')[0]}`];
      if (route === undefined) throw new Error(`unrouted request: ${method} ${url}`);
      const payload = typeof route === 'function' ? (route as Handler)(call) : route;
      if (payload === null) return new Response(null, { status: 204 });
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }),
  );
  return calls;
}

export function collection(overrides: Partial<Collection> = {}): Collection {
  return {
    id: 'c1',
    slug: 'trees',
    name: 'Trees',
    description: null,
    owner_id: 'u1',
    visibility: 'private',
    image_count: 2,
    located_count: 0,
    bbox: null,
    created_at: null,
    updated_at: null,
    is_owner: true,
    ...overrides,
  };
}

export function image(id: string, overrides: Partial<ImageItem> = {}): ImageItem {
  return {
    id,
    collection_id: 'c1',
    filename: `${id}.jpg`,
    content_type: 'image/jpeg',
    size_bytes: 2048,
    width: 800,
    height: 600,
    sha256: null,
    has_display: false,
    lat: null,
    lng: null,
    location_source: null,
    captured_at: null,
    camera_make: null,
    camera_model: null,
    external_source: null,
    external_id: null,
    properties: null,
    group_id: null,
    group_role: null,
    created_at: null,
    created_by: null,
    thumb_url: `/api/images/images/${id}/r/small?v=1`,
    display_url: `/api/images/images/${id}/display?v=1`,
    ...overrides,
  };
}

/** Let timers and the promise chains behind a stubbed `fetch` run to rest. */
export async function flush(ms = 0): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

/** The mock every page test installs for `@inertiajs/react`. */
export function inertiaMock() {
  return {
    Head: () => null,
    usePage: () => ({ url: '/admin/images', props: {} }),
    router: { visit: vi.fn(), on: vi.fn() },
    Link: ({ children, ...rest }: { children?: unknown; [key: string]: unknown }) => (
      // biome-ignore lint/suspicious/noExplicitAny: a thin passthrough stand-in for Inertia's Link
      <a {...(rest as any)}>{children as React.ReactNode}</a>
    ),
  };
}

// ---- Import fixtures -----------------------------------------------------

export function job(overrides: Partial<ImportJob> = {}): ImportJob {
  return {
    id: 'j1',
    collection_id: 'c1',
    kind: 'geojson_base64',
    status: 'completed',
    mapping: {},
    source_url: null,
    total_count: 3,
    checkpoint_index: 3,
    done_count: 3,
    duplicate_count: 0,
    failed_count: 0,
    errors: [],
    auto_run_prompts: false,
    created_at: '2026-10-29T10:00:00Z',
    updated_at: null,
    heartbeat_at: new Date().toISOString(),
    ...overrides,
  };
}

export const GEOJSON = JSON.stringify({
  type: 'FeatureCollection',
  features: [1, 2, 3].map((i) => ({
    type: 'Feature',
    properties: { image: `/9j/${'A'.repeat(40)}`, lat: 47 + i, lng: 8 + i, id: i },
    geometry: { type: 'Point', coordinates: [8, 47] },
  })),
});

export async function pickFile(input: HTMLInputElement, file: File) {
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  await act(async () => {
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await flush(20);
}
