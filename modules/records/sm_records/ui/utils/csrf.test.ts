import { afterEach, describe, expect, it, vi } from 'vitest';

/**
 * #111: the admin API refuses a write without `X-CSRF-Token`. Every JSON call
 * goes through `api.ts`'s `request()`, and the multipart import through
 * `io.ts`, so both have to send the token every signed-in page carries as the
 * framework's `csrfToken` prop (#342).
 */

type Navigate = (event: { detail: { page: { props: unknown } } }) => void;

let navigate: Navigate | undefined;

vi.mock('@inertiajs/react', () => ({
  router: {
    on: (name: string, callback: Navigate) => {
      if (name === 'navigate') navigate = callback;
      return () => undefined;
    },
  },
}));

/** Fresh copies of the clients, loaded under a page that rendered `props`. */
async function load(props: unknown) {
  vi.resetModules();
  navigate = undefined;
  // The framework's tracker subscribes to Inertia only where `window` exists.
  vi.stubGlobal('window', {});
  const text = JSON.stringify({ component: 'Records/Types', props });
  vi.stubGlobal('document', {
    querySelector: (selector: string) =>
      selector.includes('data-page') ? { textContent: text } : null,
  });
  const api = await import('./api');
  const io = await import('./io');
  return { api, io };
}

function captureFetch() {
  const fetchMock = vi
    .fn()
    .mockImplementation(async () => new Response('{"items":[]}', { status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
  return (call = 0) => new Headers((fetchMock.mock.calls[call][1] as RequestInit).headers);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the CSRF token', () => {
  it.each(['POST', 'PUT', 'PATCH', 'DELETE'])('goes out on %s', async (method) => {
    const { api } = await load({ csrfToken: 'from-the-page' });
    const headers = captureFetch();
    await api.request('/types', { method, body: '{}' });
    expect(headers().get('X-CSRF-Token')).toBe('from-the-page');
  });

  it('is left off a read', async () => {
    const { api } = await load({ csrfToken: 'tok' });
    const headers = captureFetch();
    await api.request('/types');
    expect(headers().get('X-CSRF-Token')).toBeNull();
  });

  it('goes out on the multipart import', async () => {
    const { io } = await load({ csrfToken: 'tok' });
    const headers = captureFetch();
    await io.importRecords('product', new Blob(['a,b']) as File).catch(() => undefined);
    expect(headers().get('X-CSRF-Token')).toBe('tok');
  });

  it('follows Inertia navigation onto a records screen', async () => {
    const { api } = await load({});
    const headers = captureFetch();
    navigate?.({ detail: { page: { props: { csrfToken: 'after-navigating' } } } });
    await api.request('/types', { method: 'POST', body: '{}' });
    expect(headers().get('X-CSRF-Token')).toBe('after-navigating');
  });

  it('sends no header when no page ever shared one', async () => {
    const { api } = await load({});
    const headers = captureFetch();
    await api.request('/types', { method: 'POST', body: '{}' });
    expect(headers().get('X-CSRF-Token')).toBeNull();
  });
});

describe('a CSRF refusal', () => {
  function refuse(detail: string) {
    const body = JSON.stringify({ detail });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async () => new Response(body, { status: 403 })),
    );
  }

  it("shows the module's message, not the framework's developer sentence", async () => {
    const { api } = await load({ csrfToken: 'stale' });
    refuse('CSRF token missing or invalid — read it via get_csrf_token.');
    const error = await api.request('/types', { method: 'POST', body: '{}' }).catch((e) => e);
    expect((error as Error).message).toMatch(/security token is out of date/);
    expect((error as { status: number }).status).toBe(403);
  });

  it('leaves a permission 403 as the server worded it', async () => {
    const { api } = await load({ csrfToken: 'tok' });
    refuse('Permission required: records.manage');
    const error = await api.request('/types', { method: 'POST', body: '{}' }).catch((e) => e);
    expect((error as Error).message).toBe('Permission required: records.manage');
  });
});
