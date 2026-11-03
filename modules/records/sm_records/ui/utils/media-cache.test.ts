// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { clearMediaCache, forgetMediaFile, getMediaFile } from './media-api';
import { API, PHOTO, stubLibrary } from './media-test-support';

/**
 * Review 4, code F3: the metadata cache lived as long as the JS module — in
 * an Inertia app, until a hard reload — so a file deleted on the media
 * library's own page went on showing as present. It now lasts one page
 * visit, and a file whose thumbnail fails is forgotten at once.
 */
beforeEach(() => clearMediaCache());
afterEach(() => vi.unstubAllGlobals());

describe('the media metadata cache', () => {
  it('forgets everything on an Inertia navigation, so a deleted file reads as missing', async () => {
    stubLibrary([PHOTO]);
    expect((await getMediaFile(API, PHOTO.id))?.filename).toBe('harbour.png');
    // The library after the file was deleted: every lookup is a 404.
    const gone = stubLibrary([]);
    document.dispatchEvent(new CustomEvent('inertia:navigate'));
    expect(await getMediaFile(API, PHOTO.id)).toBeNull();
    expect(gone).toHaveBeenCalledOnce();
  });

  it('forgetMediaFile drops one file and keeps the rest', async () => {
    stubLibrary([PHOTO]);
    await getMediaFile(API, PHOTO.id);
    const gone = stubLibrary([]);
    forgetMediaFile(API, PHOTO.id);
    expect(await getMediaFile(API, PHOTO.id)).toBeNull();
    expect(gone).toHaveBeenCalledOnce();
  });
});
