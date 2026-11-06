import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@inertiajs/react', () => ({ router: { on: () => () => undefined } }));

async function load() {
  vi.resetModules();
  vi.stubGlobal('document', {
    querySelector: (selector: string) =>
      selector.includes('data-page="app"')
        ? {
            textContent: JSON.stringify({
              component: 'Newsletter/Import',
              props: { csrf_token: 'tok' },
            }),
          }
        : null,
  });
  return { api: await import('./importApi'), http: await import('./http') };
}

function stubFetch(response: () => Response) {
  const fetchMock = vi.fn().mockImplementation(async () => response());
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const json =
  (body: unknown, status = 200) =>
  () =>
    new Response(JSON.stringify(body), { status });

afterEach(() => vi.unstubAllGlobals());

describe('uploadImport', () => {
  it('posts FormData with a list field and files parts, a CSRF header and no JSON type', async () => {
    const { api } = await load();
    const fetchMock = stubFetch(json({ id: 3 }, 201));
    const a = new File(['a'], 'a.csv', { type: 'text/csv' });
    const b = new File(['b'], 'b.csv', { type: 'text/csv' });
    await api.uploadImport('news', [a, b]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/newsletter/imports');
    expect(init.method).toBe('POST');
    const form = init.body as FormData;
    expect(form).toBeInstanceOf(FormData);
    expect(form.get('list')).toBe('news');
    expect(form.getAll('files')).toHaveLength(2);
    const headers = new Headers(init.headers);
    expect(headers.get('X-CSRF-Token')).toBe('tok');
    expect(headers.has('Content-Type')).toBe(false);
  });

  it('turns a 422 import_not_utf8 into an HttpError with that code', async () => {
    const { api, http } = await load();
    stubFetch(json({ detail: 'x', code: 'import_not_utf8' }, 422));
    const error = await api.uploadImport('news', []).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(http.HttpError);
    expect(http.isCode(error, 'import_not_utf8')).toBe(true);
  });
});

describe('the other calls', () => {
  it('builds the errors CSV url', async () => {
    const { api } = await load();
    expect(api.errorsCsvUrl(3)).toBe('/api/newsletter/imports/3/errors.csv');
  });

  it('creates a list, reads, maps, applies and discards', async () => {
    const { api } = await load();
    const fetchMock = stubFetch(json({ key: 'k' }, 201));
    await expect(api.createList('k', 'K')).resolves.toEqual({ key: 'k' });
    stubFetch(json({ id: 3 }));
    await api.getImport(3);
    await api.listImports();
    const mapping = { fields: { '0': 'email' }, tags: false };
    const f2 = stubFetch(json({ id: 3 }));
    await api.setMapping(3, mapping);
    await api.applyImport(3);
    f2.mockImplementation(async () => new Response(null, { status: 204 }));
    await expect(api.discardImport(3)).resolves.toBeUndefined();
    const calls = f2.mock.calls.map((c) => [c[0], (c[1] as RequestInit).method ?? 'GET']);
    expect(calls).toEqual([
      ['/api/newsletter/imports/3', 'PATCH'],
      ['/api/newsletter/imports/3/apply', 'POST'],
      ['/api/newsletter/imports/3', 'DELETE'],
    ]);
    expect(JSON.parse((f2.mock.calls[0][1] as RequestInit).body as string)).toEqual({ mapping });
    expect(fetchMock.mock.calls[0][0]).toBe('/api/newsletter/lists');
  });
});
