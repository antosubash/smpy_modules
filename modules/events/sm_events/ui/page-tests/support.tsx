/** Routed fetch with the framework's real Request/CSRF behavior intact. */
import type { ReactNode } from 'react';
import { vi } from 'vitest';
import { act } from './test-dom';

export type Call = { url: string; method: string; body: unknown; headers: Headers };
type Handler = (call: Call) => unknown;

/** A JSON body parsed, a multipart one (an upload) kept as the raw text. */
function parseBody(raw: string, type: string | null): unknown {
  return type?.includes('multipart/form-data') ? raw : JSON.parse(raw);
}

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
        body: raw ? parseBody(raw, request.headers.get('content-type')) : null,
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
    default_reminder_minutes: null,
    sources: [],
    sources_version: 'v1',
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

function Link({ href, children, ...rest }: { href: string; children?: ReactNode }) {
  return (
    <a href={href} {...rest}>
      {children}
    </a>
  );
}

export function inertiaMock() {
  return {
    Head,
    Link,
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

/** A row of the events list, as `GET /api/events/events` returns it. */
export function eventItem(overrides = {}) {
  return {
    id: 'e1',
    calendar_id: 'c1',
    parent_id: null,
    type: 'event',
    status: 'draft' as const,
    scheduled: false,
    cancelled: false,
    all_day: false,
    timezone: 'Pacific/Auckland',
    starts_at: '2026-06-30T22:00:00Z',
    ends_at: '2026-06-30T23:00:00Z',
    start_local: '2026-07-01T10:00',
    end_local: '2026-07-01T11:00',
    rrule: null,
    category_id: null,
    venue_name: null,
    revision: 4,
    publish_at: null,
    published_at: null,
    trashed: false,
    can_write: true,
    can_publish: false,
    locked: false,
    title: 'Concert',
    lang: 'en',
    ...overrides,
  };
}

export const category = { id: 'k1', slug: 'talks', names: { en: 'Talks' }, color: null };

/** An event as `GET /api/events/events/{id}` returns it. */
export function eventDetail(overrides = {}) {
  const { title: _title, lang: _lang, ...item } = eventItem();
  return {
    ...item,
    timezone: 'Europe/Vienna',
    uid: 'u@simple-module-events',
    recurrence_until: null,
    publish_at_local: null,
    attendance_mode: 'in_person' as const,
    address: null,
    online_url: null,
    latitude: null,
    longitude: null,
    organiser: null,
    image: null,
    registration_url: null,
    extra: {},
    created_at: '2026-06-01T10:00:00Z',
    updated_at: null,
    texts: {
      en: {
        slug: 'concert',
        title: 'Concert',
        summary: null,
        description: '<p>Doors at <strong>nine</strong></p>',
        seo_title: null,
        seo_description: null,
        noindex: false,
      },
    },
    overrides: [],
    sub_events: [],
    ...overrides,
  };
}

/** What a route handler returns for a 4xx/5xx: the module's `{detail, code}` envelope. */
export const refusal = (status: number, code: string, detail = 'Refused') =>
  Response.json({ detail, code }, { status });

/** A FastAPI 422: one `loc` per bad field. */
export const unprocessable = (...locs: string[][]) =>
  Response.json(
    { detail: locs.map((loc) => ({ loc: ['body', ...loc], msg: 'bad', type: 'x' })) },
    { status: 422 },
  );
