import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import en from '../locales/en.json';
import { uploadMedia } from './mediaApi';
import { UploadError } from './uploadError';

/**
 * A stand-in for XMLHttpRequest (the vitest environment is `node`). `send`
 * settles on the next tick with whatever the test queued: a response, or a
 * network failure.
 */
class FakeXhr {
  static next: { status: number; body: string } | 'network' = { status: 200, body: '{}' };
  static instances: FakeXhr[] = [];
  status = 0;
  responseText = '';
  withCredentials = false;
  responseType = '';
  upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  open = vi.fn();
  setRequestHeader = vi.fn();
  abort = vi.fn(() => this.onabort?.());

  constructor() {
    FakeXhr.instances.push(this);
  }

  send() {
    const outcome = FakeXhr.next;
    setTimeout(() => {
      if (outcome === 'network') {
        this.onerror?.();
        return;
      }
      this.status = outcome.status;
      this.responseText = outcome.body;
      this.onload?.();
    }, 0);
  }
}

const png = () => new File(['x'], 'a.png', { type: 'image/png' });
const fetchSpy = vi.fn();

describe('uploadMedia', () => {
  beforeEach(() => {
    FakeXhr.instances = [];
    vi.stubGlobal('XMLHttpRequest', FakeXhr);
    vi.stubGlobal('fetch', fetchSpy);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchSpy.mockReset();
  });

  // The block's image field (media-adapter) calls uploadMedia(file) with no
  // options; it used to take a fetch path that showed the server's English
  // `detail`. Both callers must now get the same translated rejection.
  it.each([
    ['without onProgress (block image field)', {}],
    ['with onProgress (media library)', { onProgress: vi.fn() }],
  ])('maps a 415 to the translated message %s', async (_label, options) => {
    FakeXhr.next = {
      status: 415,
      body: '{"detail":"File contents do not match an allowed image format"}',
    };
    const err = await uploadMedia(png(), options).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(UploadError);
    expect((err as UploadError).message).toBe(en.errors.upload_unsupported);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('maps a 422 detail list without echoing the English msg', async () => {
    FakeXhr.next = {
      status: 422,
      body: JSON.stringify({ detail: [{ loc: ['body', 'folder'], msg: 'Field required' }] }),
    };
    const err = (await uploadMedia(png()).catch((e: unknown) => e)) as UploadError;
    expect(err.message).toBe(en.errors.upload_failed_invalid);
    expect(err.message).not.toContain('Field required');
  });

  it('maps a network failure to the translated network message', async () => {
    FakeXhr.next = 'network';
    const err = await uploadMedia(png()).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(UploadError);
    expect((err as UploadError).message).toBe(en.errors.upload_network);
  });

  it('resolves with the parsed asset on success', async () => {
    FakeXhr.next = { status: 201, body: '{"id":7,"url":"/m/7.png"}' };
    await expect(uploadMedia(png())).resolves.toEqual({ id: 7, url: '/m/7.png' });
  });

  it('maps a 2xx with a non-JSON body to the generic translated message', async () => {
    FakeXhr.next = { status: 200, body: '<!DOCTYPE html><html>proxy</html>' };
    const err = (await uploadMedia(png()).catch((e: unknown) => e)) as UploadError;
    expect(err).toBeInstanceOf(UploadError);
    expect(err.message).toBe(en.bundle.upload_failed);
  });

  it('rejects an already-aborted signal without sending', async () => {
    const controller = new AbortController();
    controller.abort();
    const err = await uploadMedia(png(), { signal: controller.signal }).catch((e: unknown) => e);
    expect((err as DOMException).name).toBe('AbortError');
    expect(FakeXhr.instances).toHaveLength(0);
  });
});
