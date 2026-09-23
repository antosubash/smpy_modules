import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { OFFLINE_STATUS } from './api-net';
import {
  clearMediaCache,
  fileUrl,
  formatBytes,
  getMediaFile,
  isUrlValue,
  listMediaFiles,
  uploadMediaFile,
} from './media-api';
import { API, FakeXhr, json, MANUAL, PHOTO, stubLibrary, stubXhr } from './media-test-support';

beforeEach(() => clearMediaCache());
afterEach(() => vi.unstubAllGlobals());

describe('media values', () => {
  it('derives the file URL from the template, never storing it', () => {
    expect(fileUrl(API, PHOTO.id)).toBe(`/api/file-storage/files/${PHOTO.id}/download`);
    // An id is data: it cannot smuggle a path segment into the URL.
    expect(fileUrl(API, 'a/../b')).toBe('/api/file-storage/files/a%2F..%2Fb/download');
  });

  it('tells a legacy URL from an id', () => {
    expect(isUrlValue('https://cdn.example.com/a.png')).toBe(true);
    expect(isUrlValue(PHOTO.id)).toBe(false);
    expect(isUrlValue('media/products/sku-000001.jpg')).toBe(false);
  });

  it('formats sizes with the viewer locale supplying the unit', () => {
    expect(formatBytes(512)).toMatch(/512/);
    expect(formatBytes(2048)).toMatch(/2/);
    expect(formatBytes(3 * 1024 * 1024)).toMatch(/3/);
  });
});

describe('listMediaFiles', () => {
  it('pages the library and filters nothing server-side when it cannot search', async () => {
    const fetchMock = stubLibrary([PHOTO, MANUAL]);
    const page = await listMediaFiles(API, { page: 2, query: 'harb' });
    const url = new URL(String(fetchMock.mock.calls[0][0]), 'http://test');
    expect(url.searchParams.get('page')).toBe('2');
    expect(url.searchParams.get('per_page')).toBe('24');
    expect(url.searchParams.has('q')).toBe(false);
    expect(page.items.map((f) => f.id)).toEqual([PHOTO.id, MANUAL.id]);
  });

  it('sends the query under the parameter the list route declares', async () => {
    const fetchMock = stubLibrary([PHOTO, MANUAL]);
    const page = await listMediaFiles({ ...API, search_param: 'q' }, { page: 1, query: 'harb' });
    expect(String(fetchMock.mock.calls[0][0])).toContain('q=harb');
    expect(page.items.map((f) => f.id)).toEqual([PHOTO.id]);
  });

  it("surfaces file_storage's own message from a {code, message} detail", async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(json(403, { detail: { code: 'x', message: 'Not allowed here.' } })),
    );
    await expect(listMediaFiles(API, { page: 1 })).rejects.toMatchObject({
      status: 403,
      message: 'Not allowed here.',
    });
  });

  it('turns a dropped connection into the offline ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(listMediaFiles(API, { page: 1 })).rejects.toMatchObject({
      status: OFFLINE_STATUS,
    });
  });
});

describe('getMediaFile', () => {
  it('asks once per id and reads the rest from the cache', async () => {
    const fetchMock = stubLibrary([PHOTO]);
    expect(await getMediaFile(API, PHOTO.id)).toMatchObject({ filename: 'harbour.png' });
    expect(await getMediaFile(API, PHOTO.id)).toMatchObject({ filename: 'harbour.png' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('answers null for a file the library no longer has', async () => {
    stubLibrary([]);
    expect(await getMediaFile(API, PHOTO.id)).toBeNull();
  });

  it('knows a listed file without asking for it again', async () => {
    const fetchMock = stubLibrary([PHOTO]);
    await listMediaFiles(API, { page: 1 });
    await getMediaFile(API, PHOTO.id);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('drops a failure from the cache so a retry asks again', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(500, {})));
    await expect(getMediaFile(API, PHOTO.id)).rejects.toMatchObject({ status: 500 });
    const fetchMock = stubLibrary([PHOTO]);
    expect(await getMediaFile(API, PHOTO.id)).toMatchObject({ id: PHOTO.id });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('uploadMediaFile', () => {
  it('posts multipart to the upload path and reports progress', async () => {
    stubXhr();
    const progress: number[] = [];
    const handle = uploadMediaFile(API, new File(['x'], 'a.png', { type: 'image/png' }), (p) =>
      progress.push(p),
    );
    const xhr = FakeXhr.last as FakeXhr;
    expect(xhr.method).toBe('POST');
    expect(xhr.url).toBe(API.upload_path);
    expect((xhr.body as FormData).get('file')).toBeInstanceOf(File);
    xhr.progress(1, 2);
    xhr.respond(201, PHOTO);
    await expect(handle.promise).resolves.toMatchObject({ id: PHOTO.id });
    expect(progress).toEqual([50, 100]);
    // The upload primes the cache: showing it costs no second request.
    const fetchMock = stubLibrary([]);
    expect(await getMediaFile(API, PHOTO.id)).toMatchObject({ id: PHOTO.id });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects with the library's refusal", async () => {
    stubXhr();
    const handle = uploadMediaFile(API, new File(['x'], 'a.exe'), () => {});
    (FakeXhr.last as FakeXhr).respond(415, {
      detail: { code: 'file_storage.bad_type', message: 'That file type is not allowed.' },
    });
    await expect(handle.promise).rejects.toMatchObject({
      status: 415,
      message: 'That file type is not allowed.',
    });
  });

  it('rejects offline when the connection drops', async () => {
    stubXhr();
    const handle = uploadMediaFile(API, new File(['x'], 'a.png'), () => {});
    (FakeXhr.last as FakeXhr).fail();
    await expect(handle.promise).rejects.toMatchObject({ status: OFFLINE_STATUS });
  });
});
