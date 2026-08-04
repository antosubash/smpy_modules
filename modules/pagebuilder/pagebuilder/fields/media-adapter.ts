/**
 * FilePickerAdapter backed by this module's own media library.
 *
 * The image fields in every widget go through this, so the pictures on a page
 * are the ones an author uploaded to `/pagebuilder/media` — swapping one is
 * picking a different upload, not editing a path by hand.
 */

import { deleteMedia, listMedia, type MediaAssetRead, uploadMedia } from '../utils/api';
import type { FileItem, FilePickerAdapter } from './file-picker/types';

function toFileItem(asset: MediaAssetRead): FileItem {
  return {
    id: String(asset.id),
    mimeType: asset.content_type,
    fileSize: asset.size_bytes,
    url: asset.url,
  };
}

export const mediaLibraryAdapter: FilePickerAdapter = {
  async upload(file: File): Promise<FileItem> {
    return toFileItem(await uploadMedia(file));
  },

  async list({ skip = 0, take = 24 } = {}) {
    // The gallery jumps to arbitrary pages, so it uses the uploads endpoint's
    // offset mode; that mode is also what makes the response carry `total`.
    const response = await listMedia({ offset: skip, limit: take });
    return {
      items: response.items.map(toFileItem),
      totalCount: response.total ?? response.items.length,
    };
  },

  /**
   * Only reachable in the picker's "id" mode, which this module never uses:
   * assets carry a ready-to-render URL on the record, so fields store that
   * directly. There is no id → URL endpoint to call here, and inventing a
   * path from the numeric id would silently produce broken images.
   */
  getViewUrl(): string {
    throw new Error(
      'mediaLibraryAdapter stores URLs, not ids — use the picker in its default "url" mode.',
    );
  },
};
