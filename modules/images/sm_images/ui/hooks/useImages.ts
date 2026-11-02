import { useEffect, useState } from 'react';

import { listImages } from '../utils/api';
import type { GalleryFilter, ImageItem } from '../utils/types';
import { type CursorList, useCursorList } from './useCursorList';

export type Gallery = CursorList<ImageItem> & {
  filter: GalleryFilter;
  setFilter: (filter: GalleryFilter) => void;
};

/** How often, and how many times, a gallery re-reads while previews are still
 *  being made. Bounded so a failed pipeline does not poll forever. */
export const POLL_MS = 3000;
export const POLL_LIMIT = 20;

/** A collection's gallery: filter chips, cursor paging, and a short re-read
 *  while any shown image is still waiting for its `small` rendition. */
export function useImages(collectionId: string): Gallery {
  const [filter, setFilter] = useState<GalleryFilter>('all');
  const list = useCursorList(`${collectionId}:${filter}`, (cursor) =>
    listImages(collectionId, filter, cursor),
  );
  const waiting = list.items.some((image) => image.thumb_url === null);
  const [polls, setPolls] = useState(0);
  const { reload } = list;

  useEffect(() => {
    if (!waiting || polls >= POLL_LIMIT) return;
    const timer = window.setTimeout(() => {
      setPolls((n) => n + 1);
      void reload();
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [waiting, polls, reload]);

  // A new filter or an upload that brings new pending images starts a fresh budget.
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset on filter change
  useEffect(() => setPolls(0), [collectionId, filter]);

  const restart = async () => {
    setPolls(0);
    await list.reload();
  };

  return { ...list, filter, setFilter, reload: restart };
}
