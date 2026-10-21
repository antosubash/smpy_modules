import { afterEach, describe, expect, it, vi } from 'vitest';

/**
 * #110: the admin API refuses a write without `X-CSRF-Token`, and `write()` is
 * the one door every news write goes through — so it has to send the token the
 * news screens share as the `csrf_token` Inertia prop.
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
  const text = JSON.stringify({ component: 'News/NewsList', props });
  vi.stubGlobal('document', {
    querySelector: (selector: string) =>
      selector.includes('data-page="app"') ? { textContent: text } : null,
  });
  const http = await import('./http');
  const csrf = await import('./csrf');
  return { http, csrf };
}

function captureFetch() {
  const fetchMock = vi.fn().mockImplementation(async () => new Response('{}', { status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
  return (call = 0) => new Headers((fetchMock.mock.calls[call][1] as RequestInit).headers);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the CSRF token', () => {
  it('goes out on a write, from the page the server rendered', async () => {
    const { http } = await load({ csrf_token: 'from-the-page' });
    const headers = captureFetch();
    await http.write('/articles', 'POST', { title: 'x' });
    expect(headers().get('X-CSRF-Token')).toBe('from-the-page');
  });

  it.each(['PUT', 'PATCH', 'DELETE'])('goes out on %s', async (method) => {
    const { http } = await load({ csrf_token: 'tok' });
    const headers = captureFetch();
    await http.write('/articles/1', method, {});
    expect(headers().get('X-CSRF-Token')).toBe('tok');
  });

  it('is left off a read', async () => {
    const { http } = await load({ csrf_token: 'tok' });
    const headers = captureFetch();
    await http.read('/articles');
    expect(headers().get('X-CSRF-Token')).toBeNull();
  });

  it('follows Inertia navigation onto a news screen', async () => {
    // The first page was not a news screen, so it carried no token.
    const { http } = await load({});
    const headers = captureFetch();
    navigate?.({ detail: { page: { props: { csrf_token: 'after-navigating' } } } });
    await http.write('/articles', 'POST', {});
    expect(headers().get('X-CSRF-Token')).toBe('after-navigating');
  });

  it('keeps the token across a page that does not share one', async () => {
    const { http } = await load({ csrf_token: 'kept' });
    const headers = captureFetch();
    navigate?.({ detail: { page: { props: {} } } });
    await http.write('/articles', 'POST', {});
    expect(headers().get('X-CSRF-Token')).toBe('kept');
  });

  it('sends no header when no page ever shared one', async () => {
    const { http } = await load({});
    const headers = captureFetch();
    await http.write('/articles', 'POST', {});
    expect(headers().get('X-CSRF-Token')).toBeNull();
  });
});
