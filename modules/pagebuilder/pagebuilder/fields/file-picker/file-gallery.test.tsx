// @vitest-environment happy-dom
/**
 * The media picker dialog (#234): the whole library reachable by paging and
 * search, every thumbnail named, failures shown with a retry, and a slow
 * answer for an older search never overwriting the newer one. Focus trapping
 * and return are Radix's, checked in a real browser by the e2e spec.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { FileGallery } from './file-gallery';
import type { FileItem, FilePickerAdapter } from './types';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const LIBRARY: FileItem[] = Array.from({ length: 85 }, (_, i) => ({
  id: String(i + 1),
  mimeType: 'image/png',
  fileSize: 2048,
  url: `/media/${i + 1}.png`,
  name: `photo-${String(i + 1).padStart(3, '0')}.png`,
}));

function libraryAdapter(): FilePickerAdapter & { list: ReturnType<typeof vi.fn> } {
  return {
    upload: vi.fn(),
    getViewUrl: vi.fn(),
    list: vi.fn(async ({ skip = 0, take = 12, search = '' }) => {
      const hits = LIBRARY.filter((f) => f.name?.includes(search));
      return { items: hits.slice(skip, skip + take), totalCount: hits.length };
    }),
  };
}

let root: Root | null = null;

async function flush(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

async function open(adapter: FilePickerAdapter, onSelect = vi.fn()) {
  const host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  await act(async () => {
    root?.render(<FileGallery adapter={adapter} open onClose={() => {}} onSelect={onSelect} />);
  });
  await flush();
  return onSelect;
}

const dialog = () => document.querySelector('[role="dialog"]') as HTMLElement;
const picks = () =>
  Array.from(dialog().querySelectorAll<HTMLButtonElement>('ul button')).map((b) =>
    b.textContent?.trim(),
  );
const button = (name: string) =>
  Array.from(dialog().querySelectorAll('button')).find((b) => b.textContent?.trim() === name);

async function type(value: string) {
  const input = dialog().querySelector('input[type="search"]') as HTMLInputElement;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.replaceChildren();
});

describe('FileGallery', () => {
  it('is a named dialog whose thumbnails carry their file names', async () => {
    await open(libraryAdapter());
    expect(dialog().getAttribute('aria-labelledby')).toBeTruthy();
    const title = document.getElementById(dialog().getAttribute('aria-labelledby') ?? '');
    expect(title?.textContent).toBe('Select a file');
    expect(picks()[0]).toContain('photo-001.png');
    expect(picks()).toHaveLength(12);
  });

  it('pages through to the 85th file', async () => {
    const onSelect = await open(libraryAdapter());
    for (let i = 0; i < 7; i += 1) {
      await act(async () => button('Next')?.click());
      await flush();
    }
    expect(picks()).toEqual(['photo-085.png2.0 KB']);
    expect(button('Next')?.disabled).toBe(true);
    await act(async () => dialog().querySelector<HTMLButtonElement>('ul button')?.click());
    expect(onSelect).toHaveBeenCalledWith('/media/85.png', LIBRARY[84]);
  });

  it('enables Next only when a file lies beyond the page', async () => {
    const exact = libraryAdapter();
    exact.list.mockImplementation(async () => ({ items: LIBRARY.slice(0, 12), totalCount: 12 }));
    await open(exact);
    expect(button('Next')?.disabled).toBe(true);
    act(() => root?.unmount());
    document.body.replaceChildren();
    const past = libraryAdapter();
    past.list.mockImplementation(async () => ({ items: LIBRARY.slice(0, 12), totalCount: 13 }));
    await open(past);
    expect(button('Next')?.disabled).toBe(false);
  });

  it('searches by file name on the server, from page one', async () => {
    const adapter = libraryAdapter();
    await open(adapter);
    await act(async () => button('Next')?.click());
    await flush();
    await type('photo-08');
    await new Promise((resolve) => setTimeout(resolve, 300));
    await flush();
    expect(adapter.list).toHaveBeenLastCalledWith({ skip: 0, take: 12, search: 'photo-08' });
    expect(picks().map((p) => p?.slice(0, 13))).toEqual(
      ['080', '081', '082', '083', '084', '085'].map((n) => `photo-${n}.png`),
    );
  });

  it('stops the search at the 200 characters the server accepts', async () => {
    await open(libraryAdapter());
    const input = dialog().querySelector('input[type="search"]') as HTMLInputElement;
    expect(input.maxLength).toBe(200);
  });

  it('opens a new search on its first page, even after Next during the debounce', async () => {
    const adapter = libraryAdapter();
    await open(adapter);
    await type('photo-08');
    await act(async () => button('Next')?.click());
    await new Promise((resolve) => setTimeout(resolve, 300));
    await flush();
    expect(adapter.list).toHaveBeenLastCalledWith({ skip: 0, take: 12, search: 'photo-08' });
    expect(picks()).toHaveLength(6);
  });

  it("does not bring back an earlier search's page when the search returns to it", async () => {
    const adapter = libraryAdapter();
    await open(adapter);
    await act(async () => button('Next')?.click());
    await flush();
    await type('photo-0');
    await new Promise((resolve) => setTimeout(resolve, 300));
    await flush();
    await type('');
    await new Promise((resolve) => setTimeout(resolve, 300));
    await flush();
    expect(adapter.list).toHaveBeenLastCalledWith({ skip: 0, take: 12, search: '' });
    expect(picks()[0]).toContain('photo-001.png');
  });

  it('keeps Next enabled while the next page loads, so keyboard focus is not dropped', async () => {
    const adapter = libraryAdapter();
    await open(adapter);
    let release: (value: { items: FileItem[]; totalCount: number }) => void = () => {};
    adapter.list.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    await act(async () => button('Next')?.click());
    expect(button('Next')?.disabled).toBe(false);
    await act(async () => release({ items: LIBRARY.slice(12, 24), totalCount: 85 }));
    await flush();
    expect(picks()[0]).toContain('photo-013.png');
  });

  it('drops a slower answer to an older search', async () => {
    const adapter = libraryAdapter();
    let releaseOld: (value: { items: FileItem[]; totalCount: number }) => void = () => {};
    adapter.list.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          releaseOld = resolve;
        }),
    );
    await open(adapter);
    await type('photo-085');
    await new Promise((resolve) => setTimeout(resolve, 300));
    await flush();
    await act(async () => releaseOld({ items: LIBRARY.slice(0, 12), totalCount: 85 }));
    await flush();
    expect(picks().map((p) => p?.slice(0, 13))).toEqual(['photo-085.png']);
  });

  it('shows a failure with a retry that loads again', async () => {
    const adapter = libraryAdapter();
    adapter.list.mockRejectedValueOnce(new Error('offline'));
    await open(adapter);
    expect(dialog().querySelector('[role="alert"]')?.textContent).toContain('offline');
    await act(async () => button('Try again')?.click());
    await flush();
    expect(dialog().querySelector('[role="alert"]')).toBeNull();
    expect(picks()).toHaveLength(12);
  });

  it('says when a search matches nothing', async () => {
    await open(libraryAdapter());
    await type('nope');
    await new Promise((resolve) => setTimeout(resolve, 300));
    await flush();
    expect(
      dialog().querySelector('[data-testid="pagebuilder-gallery-empty"]')?.textContent,
    ).toBe('No file name matches that search.');
  });
});
