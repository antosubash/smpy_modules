import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  buildPublicListUrl,
  clampLimit,
  DEFAULT_PUBLIC_PREFIX,
  fetchPublicRecords,
  normalizePublicPrefix,
  TENANT_HEADER,
} from './public-api';

describe('normalizePublicPrefix', () => {
  it('defaults a blank prefix', () => {
    expect(normalizePublicPrefix(undefined)).toBe(DEFAULT_PUBLIC_PREFIX);
    expect(normalizePublicPrefix(null)).toBe(DEFAULT_PUBLIC_PREFIX);
    expect(normalizePublicPrefix('   ')).toBe(DEFAULT_PUBLIC_PREFIX);
  });

  it('strips one or more trailing slashes', () => {
    expect(normalizePublicPrefix('/api/records/public/')).toBe('/api/records/public');
    expect(normalizePublicPrefix('/api/records/public///')).toBe('/api/records/public');
  });

  it('leaves an already-normal prefix untouched', () => {
    expect(normalizePublicPrefix('/site/data')).toBe('/site/data');
  });

  it('falls back when trimming leaves nothing (a bare "/")', () => {
    expect(normalizePublicPrefix('/')).toBe(DEFAULT_PUBLIC_PREFIX);
  });
});

describe('clampLimit', () => {
  it('clamps to the 1–50 range', () => {
    expect(clampLimit(0)).toBe(1);
    expect(clampLimit(-5)).toBe(1);
    expect(clampLimit(51)).toBe(50);
    expect(clampLimit(200)).toBe(50);
  });

  it('keeps an in-range value, truncating a fraction', () => {
    expect(clampLimit(10)).toBe(10);
    expect(clampLimit(10.9)).toBe(10);
  });

  it('defaults a non-numeric value rather than parsing it', () => {
    expect(clampLimit(Number.NaN)).toBe(10);
    expect(clampLimit(undefined)).toBe(10);
    // A string is never parsed — '25' does not become 25, it falls back to
    // the default (which happens to also be 10, so this only proves the
    // point together with the assertion above).
    expect(clampLimit('25')).toBe(10);
  });
});

describe('buildPublicListUrl', () => {
  it('builds the base URL with just page_size when filter/sort are empty', () => {
    expect(buildPublicListUrl({ typeKey: 'products', limit: 5 })).toBe(
      `${DEFAULT_PUBLIC_PREFIX}/products?page_size=5`,
    );
  });

  it('normalises a prefix with a trailing slash', () => {
    expect(
      buildPublicListUrl({ prefix: '/api/records/public/', typeKey: 'products', limit: 5 }),
    ).toBe(`${DEFAULT_PUBLIC_PREFIX}/products?page_size=5`);
  });

  it('uses a custom prefix verbatim (normalised)', () => {
    expect(buildPublicListUrl({ prefix: '/site/data', typeKey: 'faq', limit: 25 })).toBe(
      '/site/data/faq?page_size=25',
    );
  });

  it('URL-encodes the type key', () => {
    expect(buildPublicListUrl({ typeKey: 'a b', limit: 10 })).toBe(
      `${DEFAULT_PUBLIC_PREFIX}/a%20b?page_size=10`,
    );
  });

  it('adds filter and sort only when given', () => {
    const url = buildPublicListUrl({
      typeKey: 'products',
      limit: 10,
      filter: 'status:eq:paid',
      sort: '-published_at',
    });
    const parsed = new URL(url, 'http://example.test');
    expect(parsed.pathname).toBe(`${DEFAULT_PUBLIC_PREFIX}/products`);
    expect(parsed.searchParams.get('page_size')).toBe('10');
    expect(parsed.searchParams.get('filter')).toBe('status:eq:paid');
    expect(parsed.searchParams.get('sort')).toBe('-published_at');
  });

  it('omits filter/sort when blank or whitespace-only', () => {
    const url = buildPublicListUrl({ typeKey: 'products', limit: 10, filter: '  ', sort: '' });
    expect(url).toBe(`${DEFAULT_PUBLIC_PREFIX}/products?page_size=10`);
  });

  it('clamps an out-of-range limit before building the query', () => {
    expect(buildPublicListUrl({ typeKey: 'products', limit: 999 })).toBe(
      `${DEFAULT_PUBLIC_PREFIX}/products?page_size=50`,
    );
  });

  it('adds locale only when given', () => {
    const url = buildPublicListUrl({ typeKey: 'products', limit: 10, locale: 'de' });
    const parsed = new URL(url, 'http://example.test');
    expect(parsed.searchParams.get('locale')).toBe('de');
  });

  it('omits locale when blank or whitespace-only', () => {
    const url = buildPublicListUrl({ typeKey: 'products', limit: 10, locale: '  ' });
    expect(url).toBe(`${DEFAULT_PUBLIC_PREFIX}/products?page_size=10`);
  });
});

/** `fetchPublicRecords`'s `X-Tenant-ID` header (tenancy design §J item 4) —
 *  never in the URL (`buildPublicListUrl` above never reads `options.tenant`,
 *  so two tenants' requests for the same type still share one cacheable
 *  path, per §H), only the request's headers. */
describe('fetchPublicRecords — the tenant header', () => {
  const page = { items: [], total: 0, page: 1, page_size: 10 };
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async () => new Response(JSON.stringify(page), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends X-Tenant-ID when a tenant is given', async () => {
    await fetchPublicRecords({ typeKey: 'products', limit: 5, tenant: 'acme' });
    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers[TENANT_HEADER]).toBe('acme');
  });

  it('omits the header entirely when tenant is unset, empty or whitespace-only', async () => {
    await fetchPublicRecords({ typeKey: 'products', limit: 5 });
    await fetchPublicRecords({ typeKey: 'products', limit: 5, tenant: '' });
    await fetchPublicRecords({ typeKey: 'products', limit: 5, tenant: '   ' });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    for (const call of fetchMock.mock.calls) {
      const [, init] = call as [string, RequestInit];
      const headers = init.headers as Record<string, string>;
      expect(headers[TENANT_HEADER]).toBeUndefined();
    }
  });

  it('never puts the tenant in the URL — same path for every tenant', async () => {
    await fetchPublicRecords({ typeKey: 'products', limit: 5, tenant: 'acme' });
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${DEFAULT_PUBLIC_PREFIX}/products?page_size=5`);
  });

  it('still sends credentials: omit and Accept alongside the tenant header', async () => {
    await fetchPublicRecords({ typeKey: 'products', limit: 5, tenant: 'acme' });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe('omit');
    const headers = init.headers as Record<string, string>;
    expect(headers.Accept).toBe('application/json');
  });
});
