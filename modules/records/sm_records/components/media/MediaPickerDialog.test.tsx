// @vitest-environment happy-dom
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { act, click, mount, press, settle, setValue } from '../../test-dom';
import { clearMediaCache, type MediaApi } from '../../utils/media-api';
import {
  API,
  FakeXhr,
  loadRecordsCatalog,
  MANUAL,
  PHOTO,
  stubLibrary,
  stubXhr,
} from '../../utils/media-test-support';
import { MediaPickerDialog } from './MediaPickerDialog';

async function flush(): Promise<void> {
  for (let i = 0; i < 8; i += 1) await settle();
}

const $ = <T extends Element = HTMLElement>(selector: string) =>
  document.querySelector(selector) as T | null;
const items = () =>
  Array.from(document.querySelectorAll<HTMLElement>('[data-testid="records-media-item"]'));

async function open(api: MediaApi = API, currentId: string | null = null) {
  const onPick = vi.fn();
  const onOpenChange = vi.fn();
  const view = await mount(
    <MediaPickerDialog
      api={api}
      open
      currentId={currentId}
      onOpenChange={onOpenChange}
      onPick={onPick}
    />,
  );
  await flush();
  return { view, onPick, onOpenChange };
}

beforeAll(() => loadRecordsCatalog());
beforeEach(() => clearMediaCache());
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

describe('MediaPickerDialog — the list', () => {
  it('names every item with what a sighted user sees on it, and marks the current file', async () => {
    stubLibrary([PHOTO, MANUAL]);
    const { view } = await open(API, MANUAL.id);
    const [photo, manual] = items();
    expect(photo.tagName).toBe('BUTTON');
    const name = photo.getAttribute('aria-label') ?? '';
    expect(name).toContain('harbour.png');
    expect(name).toContain('image/png');
    expect(name).toContain('uploaded');
    expect(photo.querySelector('img')?.getAttribute('src')).toBe(
      `/api/file-storage/files/${PHOTO.id}/download`,
    );
    expect(manual.getAttribute('aria-current')).toBe('true');
    expect(photo.hasAttribute('aria-current')).toBe(false);
    expect(manual.querySelector('img')).toBeNull();
    await view.unmount();
  });

  it("gives every tile the same square picture box, whatever the image's shape", async () => {
    // Review 4, ux F13: a portrait image's height beat `aspect-square` and
    // made its tile taller. Layout is not measured here (happy-dom); the
    // image is out of the flow and the box is square, capped and clipped.
    stubLibrary([PHOTO, MANUAL]);
    const { view } = await open();
    const [photo] = items();
    const box = photo.querySelector('img')?.parentElement;
    expect(box?.className.split(' ')).toEqual(
      expect.arrayContaining(['relative', 'aspect-square', 'max-h-32', 'overflow-hidden']),
    );
    expect(photo.querySelector('img')?.className).toContain('absolute inset-0');
    expect(photo.className.split(' ')).toContain('h-full');
    await view.unmount();
  });

  it('moves focus into the dialog when it opens', async () => {
    stubLibrary([PHOTO]);
    const { view } = await open();
    expect($('[data-testid="records-media-dialog"]')?.contains(document.activeElement)).toBe(true);
    await view.unmount();
  });

  it('says the library is empty, and offers the upload', async () => {
    stubLibrary([]);
    const { view } = await open();
    expect($('[data-testid="records-media-empty"]')?.textContent).toContain(
      'media library is empty',
    );
    expect($('[data-testid="records-media-upload"]')).not.toBeNull();
    await view.unmount();
  });

  it('says the library is empty even when its total counts deleted files', async () => {
    // Review 4, ux F9: `file_storage` answered `{items: [], total: 3}` (three
    // soft-deleted files), and the dialog said "No files on this page match
    // that name." with nothing typed.
    stubLibrary([], { total: 3 });
    const { view } = await open();
    expect($('[data-testid="records-media-empty"]')?.textContent).toBe(
      'The media library is empty. Upload a file to use it here.',
    );
    await view.unmount();
  });

  it('shows a load failure with a retry that asks again', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const { view } = await open();
    expect($('[role="alert"]')?.textContent).toContain("Couldn't reach the server");
    const fetchMock = stubLibrary([PHOTO]);
    await click(
      Array.from(document.querySelectorAll('button')).find((b) => b.textContent === 'Try again'),
    );
    await flush();
    expect(fetchMock).toHaveBeenCalled();
    expect(items()).toHaveLength(1);
    await view.unmount();
  });

  it('pages through a library bigger than one page', async () => {
    const fetchMock = stubLibrary([PHOTO], { total: 50 });
    const { view } = await open();
    expect($('[data-testid="records-media-page"]')?.textContent).toBe('Page 1 of 3');
    await click(
      Array.from(document.querySelectorAll('button')).find((b) => b.textContent === 'Next'),
    );
    await flush();
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain('page=2');
    expect($('[data-testid="records-media-page"]')?.textContent).toBe('Page 2 of 3');
    await view.unmount();
  });
});

describe('MediaPickerDialog — search', () => {
  it('filters the loaded page locally, and says so, when the library cannot search', async () => {
    const fetchMock = stubLibrary([PHOTO, MANUAL]);
    const { view } = await open();
    expect($('[data-testid="records-media-search-local"]')?.textContent).toContain('current page');
    await setValue($<HTMLInputElement>('#records-media-search') as HTMLInputElement, 'manual');
    await flush();
    expect(items().map((b) => b.textContent)).toEqual([expect.stringContaining('manual.pdf')]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await setValue($<HTMLInputElement>('#records-media-search') as HTMLInputElement, 'zzz');
    expect($('[data-testid="records-media-empty"]')?.textContent).toContain('on this page');
    await view.unmount();
  });

  it('asks the server when the list route declares a search parameter', async () => {
    const fetchMock = stubLibrary([PHOTO, MANUAL]);
    const { view } = await open({ ...API, search_param: 'q' });
    expect($('[data-testid="records-media-search-local"]')).toBeNull();
    await setValue($<HTMLInputElement>('#records-media-search') as HTMLInputElement, 'harb');
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
    });
    await flush();
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain('q=harb');
    expect(items()).toHaveLength(1);
    await view.unmount();
  });
});

describe('MediaPickerDialog — picking and the keyboard', () => {
  it('picks on click and closes', async () => {
    stubLibrary([PHOTO, MANUAL]);
    const { view, onPick, onOpenChange } = await open();
    await click(items()[0]);
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: PHOTO.id }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    await view.unmount();
  });

  it('moves between items with the arrow keys, Home and End', async () => {
    stubLibrary([PHOTO, MANUAL, { ...PHOTO, id: 'third', filename: 'third.png' }]);
    const { view } = await open();
    const [first, second, third] = items();
    first.focus();
    await press(first, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(second);
    await press(second, { key: 'ArrowLeft' });
    expect(document.activeElement).toBe(first);
    await press(first, { key: 'End' });
    expect(document.activeElement).toBe(third);
    await press(third, { key: 'Home' });
    expect(document.activeElement).toBe(first);
    await view.unmount();
  });

  it('closes on Escape', async () => {
    stubLibrary([PHOTO]);
    const { view, onOpenChange, onPick } = await open();
    await press(document.activeElement, { key: 'Escape' });
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onPick).not.toHaveBeenCalled();
    await view.unmount();
  });
});

describe('MediaPickerDialog — upload', () => {
  async function chooseFile(name: string) {
    const input = $<HTMLInputElement>(
      '[data-testid="records-media-upload-input"]',
    ) as HTMLInputElement;
    const file = new File(['png'], name, { type: 'image/png' });
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    await act(async () => {
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }

  it('shows progress, then picks the uploaded file', async () => {
    stubLibrary([]);
    stubXhr();
    const { view, onPick } = await open();
    await chooseFile('new.png');
    const xhr = FakeXhr.last as FakeXhr;
    expect(xhr.url).toBe(API.upload_path);
    await act(async () => xhr.progress(1, 4));
    const progress = $<HTMLProgressElement>(
      '[data-testid="records-media-upload-progress"] progress',
    );
    expect(progress?.getAttribute('value')).toBe('25');
    expect($('[data-testid="records-media-upload-progress"]')?.textContent).toContain('new.png');
    await act(async () => xhr.respond(201, { ...PHOTO, filename: 'new.png' }));
    await flush();
    expect(onPick).toHaveBeenCalledWith(
      expect.objectContaining({ id: PHOTO.id, filename: 'new.png' }),
    );
    await view.unmount();
  });

  it("shows the library's refusal and picks nothing", async () => {
    stubLibrary([]);
    stubXhr();
    const { view, onPick } = await open();
    await chooseFile('huge.png');
    await act(async () =>
      (FakeXhr.last as FakeXhr).respond(413, {
        detail: { code: 'file_storage.too_large', message: 'File is too large.' },
      }),
    );
    await flush();
    const alert = $('[data-testid="records-media-upload-error"]');
    expect(alert?.getAttribute('role')).toBe('alert');
    expect(alert?.textContent).toContain('File is too large.');
    expect(onPick).not.toHaveBeenCalled();
    expect($<HTMLButtonElement>('[data-testid="records-media-upload"]')?.disabled).toBe(false);
    await view.unmount();
  });

  it('says nothing was lost when the connection drops mid-upload', async () => {
    stubLibrary([]);
    stubXhr();
    const { view } = await open();
    await chooseFile('a.png');
    await act(async () => (FakeXhr.last as FakeXhr).fail());
    await flush();
    expect($('[data-testid="records-media-upload-error"]')?.textContent).toContain(
      "Couldn't reach the server",
    );
    await view.unmount();
  });
});
