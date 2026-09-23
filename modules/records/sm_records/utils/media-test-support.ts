/**
 * Fixtures for the `media` picker's tests: a `media_api` prop, a few stored
 * files, a `fetch` that answers like `file_storage`'s list and metadata
 * routes, and an `XMLHttpRequest` stand-in the upload tests drive by hand.
 *
 * Not a test file (no `.test.` in the name), so vitest leaves it alone; it
 * sits beside `test-dom.tsx`'s role for the DOM, for the network.
 */

import { configureI18n } from '@simple-module-py/i18n';
import { vi } from 'vitest';

import catalog from '../locales/en.json';
import type { MediaApi, MediaFile } from './media-api';

function flatten(node: unknown, prefix: string, out: Record<string, string>): void {
  if (typeof node === 'string') {
    out[prefix] = node;
    return;
  }
  for (const [key, child] of Object.entries(node as Record<string, unknown>)) {
    flatten(child, `${prefix}.${key}`, out);
  }
}

/** Configure i18next with this module's real catalog, as the host does at
 *  boot — so `{name}` placeholders interpolate and a test can assert what a
 *  person (or a screen reader) actually gets. Per test file: vitest isolates
 *  modules between files, so no other file sees it. */
export function loadRecordsCatalog(): void {
  const messages: Record<string, string> = {};
  flatten(catalog, 'records', messages);
  configureI18n({ locale: 'en', messages });
}

export const API: MediaApi = {
  prefix: '/api/file-storage',
  list_path: '/api/file-storage/files',
  upload_path: '/api/file-storage/upload',
  file_url_template: '/api/file-storage/files/{id}/download',
  meta_url_template: '/api/file-storage/files/{id}',
  search_param: null,
};

export const PHOTO: MediaFile = {
  id: '11111111-1111-4111-8111-111111111111',
  filename: 'harbour.png',
  content_type: 'image/png',
  size_bytes: 2048,
  created_at: '2026-09-20T10:00:00+00:00',
};

export const MANUAL: MediaFile = {
  id: '22222222-2222-4222-8222-222222222222',
  filename: 'manual.pdf',
  content_type: 'application/pdf',
  size_bytes: 3 * 1024 * 1024,
  created_at: '2026-09-21T10:00:00+00:00',
};

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status >= 400 ? 'Error' : 'OK',
    headers: { 'content-type': 'application/json' },
  });
}

/** A `fetch` over a fixed library: the list route pages `files` (and
 *  honours `q` when the test's API declares it), the metadata route answers
 *  for each file and 404s for anything else. Returns the mock so a test can
 *  read the URLs it was called with. */
export function stubLibrary(files: MediaFile[], options: { total?: number } = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://test');
    if (url.pathname === API.list_path) {
      const q = (url.searchParams.get('q') ?? '').toLowerCase();
      const items = q ? files.filter((f) => f.filename.toLowerCase().includes(q)) : files;
      return json(200, {
        items,
        total: options.total ?? items.length,
        page: Number(url.searchParams.get('page') ?? 1),
        per_page: Number(url.searchParams.get('per_page') ?? 24),
      });
    }
    const match = files.find((f) => url.pathname === `${API.list_path}/${f.id}`);
    return match
      ? json(200, match)
      : json(404, { detail: { code: 'file_storage.not_found', message: 'File not found.' } });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** `XMLHttpRequest`, reduced to what `uploadMediaFile` touches. `last` is the
 *  request a test answers with `progress`/`respond`/`fail`. */
export class FakeXhr {
  static last: FakeXhr | null = null;
  method = '';
  url = '';
  body: unknown = null;
  status = 0;
  statusText = '';
  responseText = '';
  withCredentials = false;
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader() {}
  send(body: unknown) {
    this.body = body;
    FakeXhr.last = this;
  }
  abort() {
    this.onabort?.();
  }
  progress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total } as ProgressEvent);
  }
  respond(status: number, body: unknown) {
    this.status = status;
    this.statusText = status >= 400 ? 'Error' : 'Created';
    this.responseText = JSON.stringify(body);
    this.onload?.();
  }
  fail() {
    this.onerror?.();
  }
}

export function stubXhr(): void {
  FakeXhr.last = null;
  vi.stubGlobal('XMLHttpRequest', FakeXhr);
}
