// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';

import { FileGallery } from './lazy-file-gallery';
import type { FileItem, FilePickerAdapter } from './types';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it('opens the lazy gallery with the original picker props and callbacks', async () => {
  const item: FileItem = {
    id: 'cover',
    url: '/media/cover.webp',
    name: 'cover.webp',
    mimeType: 'image/webp',
    fileSize: 1024,
    altText: 'Cover',
  };
  const adapter: FilePickerAdapter = {
    upload: vi.fn(),
    getViewUrl: vi.fn(),
    list: vi.fn(async () => ({ items: [item], totalCount: 1 })),
  };
  const onSelect = vi.fn();
  const onClose = vi.fn();
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const render = (open: boolean) =>
    root.render(
      <FileGallery adapter={adapter} open={open} onClose={onClose} onSelect={onSelect} />,
    );
  try {
    await act(async () => render(false));
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(adapter.list).not.toHaveBeenCalled();

    await act(async () => render(true));
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    const pick = document.querySelector<HTMLButtonElement>('[role="dialog"] ul button');
    expect(pick?.textContent).toContain('cover.webp');
    await act(async () => pick?.click());
    expect(onSelect).toHaveBeenCalledWith('/media/cover.webp', item);
    expect(onClose).toHaveBeenCalledOnce();

    await act(async () => render(false));
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  } finally {
    act(() => root.unmount());
    host.remove();
  }
});
