import { afterEach, describe, expect, it, vi } from 'vitest';

import en from '../../locales/en.json';

/**
 * #126: the AI API refuses a write without `X-CSRF-Token`. The token is the
 * framework's `csrfToken` shared prop (#342); the save and the
 * slot actions have to send it back, and the read must not.
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

async function load(props: unknown) {
  vi.resetModules();
  navigate = undefined;
  // The framework's tracker subscribes to Inertia only where `window` exists.
  vi.stubGlobal('window', {});
  const text = JSON.stringify({ component: 'AI/Settings', props });
  vi.stubGlobal('document', {
    querySelector: (selector: string) =>
      selector.includes('data-page') ? { textContent: text } : null,
  });
  return import('./api');
}

function captureFetch(status = 200, body = '{}') {
  const fetchMock = vi.fn().mockImplementation(async () => new Response(body, { status }));
  vi.stubGlobal('fetch', fetchMock);
  return (call = 0) => new Headers((fetchMock.mock.calls[call][1] as RequestInit).headers);
}

const slot = { provider: 'anthropic', model: 'm', base_url: '', api_key: '', clear_key: false };

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the CSRF token', () => {
  it('goes out on a save', async () => {
    const api = await load({ csrfToken: 'from-the-page' });
    const headers = captureFetch();
    await api.saveSettings(slot, slot, false);
    expect(headers().get('X-CSRF-Token')).toBe('from-the-page');
  });

  it.each(['testSlot', 'listModels'] as const)('goes out on %s', async (name) => {
    const api = await load({ csrfToken: 'tok' });
    const headers = captureFetch();
    await api[name]('chat');
    expect(headers().get('X-CSRF-Token')).toBe('tok');
  });

  it('is left off the read', async () => {
    const api = await load({ csrfToken: 'tok' });
    const headers = captureFetch();
    await api.loadSettings();
    expect(headers().get('X-CSRF-Token')).toBeNull();
  });

  it('follows Inertia navigation onto the settings screen', async () => {
    const api = await load({});
    const headers = captureFetch();
    navigate?.({ detail: { page: { props: { csrfToken: 'after-navigating' } } } });
    await api.saveSettings(slot, slot, false);
    expect(headers().get('X-CSRF-Token')).toBe('after-navigating');
  });

  it('sends no header when no page ever shared one', async () => {
    const api = await load({});
    const headers = captureFetch();
    await api.saveSettings(slot, slot, false);
    expect(headers().get('X-CSRF-Token')).toBeNull();
  });
});

describe('a CSRF refusal', () => {
  it("shows the module's message, not the framework's developer sentence", async () => {
    const api = await load({ csrfToken: 'stale' });
    captureFetch(403, JSON.stringify({ detail: 'CSRF token missing or invalid — read it.' }));
    const error = await api.saveSettings(slot, slot, false).catch((e: unknown) => e);
    expect((error as Error).message).toBe(en.api.csrf_failed);
  });

  it('leaves a permission 403 as the server worded it', async () => {
    const api = await load({ csrfToken: 'tok' });
    const detail = 'Permission required: ai.manage';
    captureFetch(403, JSON.stringify({ detail }));
    const error = await api.saveSettings(slot, slot, false).catch((e: unknown) => e);
    expect((error as Error).message).toBe(detail);
  });
});
