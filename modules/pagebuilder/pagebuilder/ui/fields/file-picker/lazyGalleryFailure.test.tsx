// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';

// The chunk never arrives: offline, or a deploy replaced the hashed file.
vi.mock('./file-gallery', () => {
  throw new Error('Failed to fetch dynamically imported module');
});

import { mediaLibraryAdapter } from '../media-adapter';
import { FileGallery } from './lazy-file-gallery';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it('a gallery chunk that will not load stays inside the picker, with Try again and Close', async () => {
  const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
  const onClose = vi.fn();
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => {
    root.render(
      <>
        <p>editor</p>
        <FileGallery adapter={mediaLibraryAdapter} open onClose={onClose} onSelect={() => {}} />
      </>,
    );
  });
  const failed = () => host.querySelector('[data-testid="gallery-load-failed"]');
  await vi.waitFor(() => expect(failed()).not.toBeNull());
  // What surrounds the picker is still mounted.
  expect(host.textContent).toContain('editor');

  const buttons = () => [...(failed()?.querySelectorAll('button') ?? [])];
  const first = failed();
  await act(async () => buttons()[1]?.click()); // Try again
  // Asked again, failed again: a new notice, not the old one left standing.
  await vi.waitFor(() => expect(failed()).not.toBe(first));
  await vi.waitFor(() => expect(failed()).not.toBeNull());
  await act(async () => buttons()[0]?.click()); // Close
  expect(onClose).toHaveBeenCalledTimes(1);

  await act(async () => root.unmount());
  host.remove();
  errors.mockRestore();
});
