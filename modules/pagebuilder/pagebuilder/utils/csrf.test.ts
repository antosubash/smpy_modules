import { afterEach, describe, expect, it, vi } from 'vitest';

import en from '../locales/en.json';

/**
 * #126: the admin API refuses a write without `X-CSRF-Token`. `request()` is
 * the door every JSON write goes through, and `uploadMedia` the one for
 * uploads, so both have to send the token the pagebuilder screens share as
 * the `csrf_token` Inertia prop.
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

/** A fresh copy of the modules, loaded under a page that rendered `props`. */
async function load(props: unknown) {
  vi.resetModules();
  navigate = undefined;
  const text = JSON.stringify({ component: 'PageBuilder/PageList', props });
  vi.stubGlobal('document', {
    querySelector: (selector: string) =>
      selector.includes('data-page="app"') ? { textContent: text } : null,
  });
  const request = await import('./request');
  const media = await import('./mediaApi');
  return { request, media };
}

function captureFetch(status = 200, body = '{}') {
  const fetchMock = vi.fn().mockImplementation(async () => new Response(body, { status }));
  vi.stubGlobal('fetch', fetchMock);
  return (call = 0) => new Headers((fetchMock.mock.calls[call][1] as RequestInit).headers);
}

/** Just enough XMLHttpRequest to see the headers and answer `status`. */
function captureXhr(status = 201, body = '{"id":1}') {
  const headers: Record<string, string> = {};
  class FakeXhr {
    status = 0;
    responseText = '';
    upload = { onprogress: null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;
    onloadend: (() => void) | null = null;
    open() {}
    setRequestHeader(name: string, value: string) {
      headers[name] = value;
    }
    send() {
      setTimeout(() => {
        this.status = status;
        this.responseText = body;
        this.onload?.();
      }, 0);
    }
  }
  vi.stubGlobal('XMLHttpRequest', FakeXhr);
  return headers;
}

const png = () => new File(['x'], 'a.png', { type: 'image/png' });
const REFUSAL = JSON.stringify({
  detail: 'CSRF token missing or invalid — read it via get_csrf_token.',
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the CSRF token', () => {
  it.each(['POST', 'PUT', 'PATCH', 'DELETE'])('goes out on %s', async (method) => {
    const { request } = await load({ csrf_token: 'from-the-page' });
    const headers = captureFetch();
    await request.request('/pages/1', { method, body: '{}' });
    expect(headers().get('X-CSRF-Token')).toBe('from-the-page');
  });

  it('is left off a read', async () => {
    const { request } = await load({ csrf_token: 'tok' });
    const headers = captureFetch();
    await request.request('/pages');
    expect(headers().get('X-CSRF-Token')).toBeNull();
  });

  it('goes out on a media upload', async () => {
    const { media } = await load({ csrf_token: 'tok' });
    const headers = captureXhr();
    await media.uploadMedia(png());
    expect(headers['X-CSRF-Token']).toBe('tok');
  });

  it('follows Inertia navigation onto a pagebuilder screen', async () => {
    const { request } = await load({});
    const headers = captureFetch();
    navigate?.({ detail: { page: { props: { csrf_token: 'after-navigating' } } } });
    await request.request('/pages', { method: 'POST', body: '{}' });
    expect(headers().get('X-CSRF-Token')).toBe('after-navigating');
  });

  it('keeps the token across a page that does not share one', async () => {
    const { request } = await load({ csrf_token: 'kept' });
    const headers = captureFetch();
    navigate?.({ detail: { page: { props: {} } } });
    await request.request('/pages', { method: 'POST', body: '{}' });
    expect(headers().get('X-CSRF-Token')).toBe('kept');
  });

  it('sends no header when no page ever shared one', async () => {
    const { request, media } = await load({});
    const headers = captureFetch();
    await request.request('/pages', { method: 'POST', body: '{}' });
    expect(headers().get('X-CSRF-Token')).toBeNull();
    const xhrHeaders = captureXhr();
    await media.uploadMedia(png());
    expect(xhrHeaders['X-CSRF-Token']).toBeUndefined();
  });
});

describe('a CSRF refusal', () => {
  it("shows the module's message, not the framework's developer sentence", async () => {
    const { request } = await load({ csrf_token: 'stale' });
    captureFetch(403, REFUSAL);
    const error = await request
      .request('/pages', { method: 'POST', body: '{}' })
      .catch((e: unknown) => e);
    expect((error as Error).message).toBe(en.errors.csrf_failed);
  });

  it('leaves a permission 403 as the server worded it', async () => {
    const { request } = await load({ csrf_token: 'tok' });
    const detail = 'Permission required: pagebuilder.publish';
    captureFetch(403, JSON.stringify({ detail }));
    const error = await request
      .request('/pages/1/publish', { method: 'POST' })
      .catch((e: unknown) => e);
    expect((error as Error).message).toBe(detail);
  });

  it('reads as a stale page on an upload, not as a missing permission', async () => {
    const { media } = await load({ csrf_token: 'stale' });
    captureXhr(403, REFUSAL);
    const error = await media.uploadMedia(png()).catch((e: unknown) => e);
    expect((error as Error).message).toBe(en.errors.csrf_failed);
  });

  it('keeps the permission message for an upload refused by permission', async () => {
    const { media } = await load({ csrf_token: 'tok' });
    captureXhr(403, JSON.stringify({ detail: 'Permission required: pagebuilder.edit' }));
    const error = await media.uploadMedia(png()).catch((e: unknown) => e);
    expect((error as Error).message).toBe(en.errors.upload_forbidden);
  });
});
