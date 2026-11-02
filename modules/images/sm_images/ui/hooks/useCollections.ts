import { useState } from 'react';

import { listCollections } from '../utils/api';
import type { Collection, CollectionFilter, Page } from '../utils/types';
import { type CursorList, useCursorList } from './useCursorList';

export type Collections = CursorList<Collection> & {
  filter: CollectionFilter;
  setFilter: (filter: CollectionFilter) => void;
};

/** The collections screen's list: the server's first page for "all", the API
 *  for every other filter and every page after. */
export function useCollections(initial: Page<Collection>): Collections {
  const [filter, setFilter] = useState<CollectionFilter>('all');
  const list = useCursorList(filter, (cursor) => listCollections(filter, cursor), {
    key: 'all',
    page: initial,
  });
  return { ...list, filter, setFilter };
}
