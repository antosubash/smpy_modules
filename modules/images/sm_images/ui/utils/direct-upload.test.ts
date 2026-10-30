import { afterEach, describe, expect, it, vi } from 'vitest';

import { uploadFile } from './direct-upload';

type Seen = { url: string; method: string; body: unknown };

/** A `fetch` that answers by `"METHOD url"` and records what it was sent. */
function stub(routes: Record<string, () => Response>): Seen[] {
  const seen: Seen[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const method = (init?.method ?? 'GET').toUpperCase();
      const url = String(input);
      seen.push({ url, method, body: init?.body });
      const route = routes[`${method} ${url}`];
      if (!route) throw new Error(`unrouted: ${method} ${url}`);
      return route();
    }),
  );
  return seen;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const created = { status: 'created', id: 'i1', filename: 'big.jpg', code: null, detail: null };
const THRESHOLD = 10;

afterEach(() => vi.unstubAllGlobals());

describe('uploadFile', () => {
  it('sends a file at or under the threshold as one multipart request', async () => {
    const seen = stub({
      'POST /api/images/collections/c1/images': () => json({ results: [created] }),
    });
    const result = await uploadFile(
      'c1',
      new File([new Uint8Array(THRESHOLD)], 'a.jpg'),
      THRESHOLD,
    );
    expect(result.status).toBe('created');
    expect(seen).toHaveLength(1);
    expect(seen[0].body).toBeInstanceOf(FormData);
  });

  it('sends a larger file by direct upload: start, a relay PUT per part, complete', async () => {
    const seen = stub({
      'POST /api/images/collections/c1/uploads': () =>
        json(
          {
            upload_id: 'tok',
            part_size: 6,
            part_urls: ['/api/images/uploads/tok/parts/1', '/api/images/uploads/tok/parts/2'],
            direct: false,
          },
          201,
        ),
      'PUT /api/images/uploads/tok/parts/1': () => json({ no: 1, etag: 'e1', size: 6 }),
      'PUT /api/images/uploads/tok/parts/2': () => json({ no: 2, etag: 'e2', size: 5 }),
      'POST /api/images/uploads/tok/complete': () => json(created),
    });
    const file = new File([new Uint8Array(11)], 'big.jpg', { type: 'image/jpeg' });
    const result = await uploadFile('c1', file, THRESHOLD);

    expect(result.status).toBe('created');
    expect(seen.map((s) => `${s.method} ${s.url}`)).toEqual([
      'POST /api/images/collections/c1/uploads',
      'PUT /api/images/uploads/tok/parts/1',
      'PUT /api/images/uploads/tok/parts/2',
      'POST /api/images/uploads/tok/complete',
    ]);
    expect(JSON.parse(seen[0].body as string)).toEqual({
      filename: 'big.jpg',
      size: 11,
      content_type: 'image/jpeg',
    });
    expect((seen[1].body as Blob).size).toBe(6);
    expect((seen[2].body as Blob).size).toBe(5);
    expect(JSON.parse(seen[3].body as string)).toEqual({
      parts: [
        { no: 1, etag: 'e1' },
        { no: 2, etag: 'e2' },
      ],
      filename: 'big.jpg',
    });
  });

  it('claims the ETag a presigned storage URL answers with', async () => {
    const seen = stub({
      'POST /api/images/collections/c1/uploads': () =>
        json(
          { upload_id: 'tok', part_size: 20, part_urls: ['https://s3.test/p1'], direct: true },
          201,
        ),
      'PUT https://s3.test/p1': () =>
        new Response(null, { status: 200, headers: { ETag: '"abc"' } }),
      'POST /api/images/uploads/tok/complete': () => json(created),
    });
    await uploadFile('c1', new File([new Uint8Array(11)], 'big.jpg'), THRESHOLD);
    expect(JSON.parse(seen[2].body as string).parts).toEqual([{ no: 1, etag: '"abc"' }]);
  });

  it("reports a refused direct upload as that file's error, with its code", async () => {
    stub({
      'POST /api/images/collections/c1/uploads': () =>
        json({ detail: 'no', code: 'direct_upload_unsupported' }, 503),
    });
    const result = await uploadFile('c1', new File([new Uint8Array(11)], 'big.jpg'), THRESHOLD);
    expect(result).toMatchObject({ status: 'error', code: 'direct_upload_unsupported' });
  });
});
