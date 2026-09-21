import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, buildFilterParam, getType, OFFLINE_STATUS, previewSchema } from './api';
import type { ApiErrorBody } from './types';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: 'Error',
    headers: { 'content-type': 'application/json' },
  });
}

/**
 * `ApiError` is what every page branches on (`status === 409`, walking
 * `body.errors`), so its shape has to be exactly what the API sends, not a
 * flattened message string.
 */
describe('ApiError', () => {
  it('carries the status and parsed body', () => {
    const body = { detail: 'stale', current: { uuid: 'x' } } as unknown as ApiErrorBody;
    const err = new ApiError(409, body, 'stale');
    expect(err.status).toBe(409);
    expect(err.body).toEqual(body);
    expect(err.message).toBe('stale');
    expect(err).toBeInstanceOf(Error);
  });

  it('is distinguishable from a plain Error via instanceof', () => {
    const err: unknown = new ApiError(422, null, 'bad');
    expect(err instanceof ApiError).toBe(true);
  });
});

describe('request() error shaping', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('prefers the detail string for a 409', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(409, { detail: 'stale', current: { key: 'faq' } })),
    );

    await expect(getType('faq')).rejects.toMatchObject({
      status: 409,
      message: 'stale',
      body: { detail: 'stale', current: { key: 'faq' } },
    });
  });

  it('summarizes a 422 error list instead of using detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(422, {
          detail: 'Validation failed',
          errors: [{ field: 'label', message: 'is required' }],
        }),
      ),
    );

    await expect(getType('faq')).rejects.toMatchObject({
      status: 422,
      message: 'label: is required',
    });
  });

  /** UX review R12a: `fetch` rejects rather than resolving when the server
   *  isn't there, and the raw rejection ("Failed to fetch") used to land in a
   *  toast over a form full of unsaved work. */
  it('rethrows a dropped connection as an offline ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    const err = await getType('faq').catch((caught: unknown) => caught);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: OFFLINE_STATUS, body: null });
    expect((err as ApiError).message).toContain("Couldn't reach the server");
  });

  /** R12b: a session that expired while the page was open is not a failed
   *  request, and `Request failed (401 Unauthorized)` tells nobody that. */
  it('replaces a 401 with a sign-in message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse(401, { detail: 'Not authenticated' })),
    );

    const err = await getType('faq').catch((caught: unknown) => caught);
    expect(err).toMatchObject({ status: 401 });
    expect((err as ApiError).message).toContain('session has expired');
  });

  it('falls back to the status line when the body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response('<html>nope</html>', { status: 500, statusText: 'Server Error' }),
        ),
    );

    await expect(getType('faq')).rejects.toMatchObject({
      status: 500,
      message: 'Request failed (500 Server Error)',
      body: null,
    });
  });
});

/**
 * F5: a `display_field`/`slug_field`-only edit must not preview as "No
 * changes" — the server treats an omitted pointer as "unchanged" and an
 * explicit `null` as "clear", so the client has to send both pointers
 * (not just `fields`) on every preview.
 */
describe('previewSchema', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends fields alongside both pointers, converting "cleared" to null', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { kind: 'additive' }));
    vi.stubGlobal('fetch', fetchMock);

    await previewSchema('faq', { fields: [], display_field: null, slug_field: 'slug' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      fields: [],
      display_field: null,
      slug_field: 'slug',
    });
  });
});

describe('buildFilterParam', () => {
  it('encodes field:op:value for a scalar', () => {
    expect(buildFilterParam('price', 'gt', 100)).toBe('price:gt:100');
    expect(buildFilterParam('title', 'contains', 'foo')).toBe('title:contains:foo');
  });

  it('comma-joins an array for `in`', () => {
    expect(buildFilterParam('status', 'in', ['draft', 'published'])).toBe(
      'status:in:draft,published',
    );
  });

  it('joins a single-item array without a trailing comma', () => {
    expect(buildFilterParam('status', 'in', ['draft'])).toBe('status:in:draft');
  });

  it('stringifies a boolean value', () => {
    expect(buildFilterParam('active', 'eq', true)).toBe('active:eq:true');
  });

  it('handles is_null with a boolean-ish string value', () => {
    expect(buildFilterParam('archived_at', 'is_null', 'true')).toBe('archived_at:is_null:true');
  });
});
