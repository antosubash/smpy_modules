/** Routed fetch with the framework's real Request/CSRF behavior intact. */
import { vi } from 'vitest';
import { act } from './test-dom';

export type Call = { url: string; method: string; body: unknown; headers: Headers };
type Handler = (call: Call) => unknown;

export function stubFetch(routes: Record<string, Handler | unknown>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request =
        input instanceof Request ? input : new Request(new URL(String(input), location.href), init);
      const url = new URL(request.url);
      const raw = await request.text();
      const call = {
        url: url.pathname + url.search,
        method: request.method,
        body: raw ? JSON.parse(raw) : null,
        headers: request.headers,
      };
      calls.push(call);
      const route = routes[`${call.method} ${url.pathname}`];
      if (route === undefined) throw new Error(`unrouted request: ${call.method} ${url.pathname}`);
      const result = typeof route === 'function' ? await (route as Handler)(call) : route;
      if (result instanceof Response) return result;
      return result === null ? new Response(null, { status: 204 }) : Response.json(result);
    }),
  );
  return calls;
}

export function calendar(overrides = {}) {
  return {
    id: 'c1',
    name: 'Team',
    slug: 'team',
    color: '#2563eb',
    description: null,
    visibility: 'private' as const,
    owner_id: 'u1',
    owner_name: 'Olga Owner',
    default_timezone: 'Europe/Vienna',
    sources: [],
    created_at: '2026-11-17T12:00:00Z',
    updated_at: null,
    deleted_at: null,
    can_edit: true,
    can_own: true,
    can_write_events: true,
    can_publish: false,
    ...overrides,
  };
}

export async function flush(ms = 10) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

function Head() {
  return null;
}

export function inertiaMock() {
  return {
    Head,
    usePage: () => ({ url: '/admin/events/calendars', props: {} }),
    router: { visit: vi.fn(), on: vi.fn() },
  };
}

export function button(text: string, root: ParentNode = document) {
  const result = [...root.querySelectorAll('button')].find((b) => b.textContent === text);
  if (!result) throw new Error(`Missing button: ${text}`);
  return result;
}

export function field(id: string) {
  const result = document.getElementById(id);
  if (
    !(
      result instanceof HTMLInputElement ||
      result instanceof HTMLSelectElement ||
      result instanceof HTMLTextAreaElement
    )
  ) {
    throw new Error(`Missing field: ${id}`);
  }
  return result;
}

export async function submit() {
  const form = document.querySelector('[role="dialog"] form');
  if (!form) throw new Error('Missing dialog form');
  await act(async () => {
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
}
