// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { initAnalytics, track } from './tracker';
import { matchPath } from './trackingPaths';

const property = {
  id: 'one',
  kind: 'application' as const,
  route_patterns: ['/records/:id'],
  utm_parameters: ['utm_source'],
  event_allowlist: { download: ['format'] },
};

describe('analytics tracker', () => {
  beforeEach(() => {
    window.history.replaceState(
      {},
      '',
      'http://localhost:3000/records/secret?token=private&utm_source=mail#secret',
    );
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    Object.defineProperty(navigator, 'doNotTrack', { configurable: true, value: '0' });
    Object.defineProperty(navigator, 'globalPrivacyControl', { configurable: true, value: false });
  });
  afterEach(() => {
    initAnalytics({ properties: [] });
    vi.unstubAllGlobals();
  });

  it('matches only whole configured paths and strips query and fragments', () => {
    expect(matchPath('/records/private?token=x#secret', ['/records/:id'], 'application')).toBe(
      '/records/:id',
    );
    expect(matchPath('/records/private/more', ['/records/:id'], 'application')).toBeNull();
    expect(matchPath('/de/p/welcome?token=x', ['/de/p/:slug'], 'public')).toBe('/de/p/welcome');
    expect(matchPath('/analytics/reports', ['/analytics/:id'], 'application')).toBeNull();
    expect(matchPath('/settings/profile', ['/settings/:id'], 'application')).toBeNull();
  });
  it('omits encoded excluded routes even when a public route would match', () => {
    expect(matchPath('/%61uth/signin', ['/:area/:page'], 'public')).toBeNull();
    expect(matchPath('/%73ettings/profile', ['/:area/:page'], 'public')).toBeNull();
    expect(matchPath('/%61nalytics/report', ['/:area/:page'], 'public')).toBeNull();
    expect(matchPath('/nested%2Fsettings/profile', ['/:area/:page'], 'public')).toBeNull();
    expect(matchPath('/bad%XX/path', ['/:area/:page'], 'public')).toBeNull();
  });
  it('sends UUID v4 event IDs when randomUUID is unavailable on HTTP', async () => {
    const original = crypto;
    vi.stubGlobal('crypto', { getRandomValues: original.getRandomValues.bind(original) });
    initAnalytics({ properties: [property] });
    await track('download', { format: 'pdf' });
    expect(fetch).toHaveBeenCalledTimes(2);
    const ids = vi
      .mocked(fetch)
      .mock.calls.map(([, init]) => JSON.parse(String(init?.body)).event_id);
    expect(ids[0]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(ids[1]).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(ids[0]).not.toBe(ids[1]);
  });
  it('sends only normalized route, enabled UTM fields and allowlisted properties', async () => {
    initAnalytics({ properties: [property] });
    await track('download', { format: 'pdf', email: 'private@example.com' });
    const calls = vi.mocked(fetch).mock.calls;
    expect(calls).toHaveLength(2);
    const pageview = JSON.parse(String(calls[0][1]?.body));
    expect(pageview.path).toBe('/records/:id');
    expect(pageview.utm).toEqual({ utm_source: 'mail' });
    expect(pageview).not.toHaveProperty('title');
    const event = JSON.parse(String(calls[1][1]?.body));
    expect(event.properties).toEqual({ format: 'pdf' });
    expect(event.name).toBe('download');
    expect(calls[0][1]?.credentials).toBe('same-origin');
  });
  it('does not collect when privacy signals or opt-out are present', async () => {
    Object.defineProperty(navigator, 'globalPrivacyControl', { configurable: true, value: true });
    initAnalytics({ properties: [property] });
    await track('download', {});
    expect(fetch).not.toHaveBeenCalled();
    Object.defineProperty(navigator, 'globalPrivacyControl', { configurable: true, value: false });
    initAnalytics({ properties: [] });
    await track('download', {});
    expect(fetch).not.toHaveBeenCalled();
  });
  it('ignores unknown events and collection failures without replay', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('offline'));
    initAnalytics({ properties: [property] });
    await track('unknown', {});
    await track('', {});
    await track('download', {});
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
