import { useCallback } from 'react';

import { deleteGroup, listGroups } from '../utils/api-groups';
import type { GroupItem } from '../utils/types';
import { type CursorList, useCursorList } from './useCursorList';

export type Groups = CursorList<GroupItem> & {
  remove: (group: GroupItem) => Promise<void>;
};

/** A collection's groups, key-ordered and paged, with their first members. */
export function useGroups(collectionId: string): Groups {
  const list = useCursorList(collectionId, (cursor) => listGroups(collectionId, cursor));
  const { reload } = list;
  const remove = useCallback(
    async (group: GroupItem) => {
      await deleteGroup(group.id);
      await reload();
    },
    [reload],
  );
  return { ...list, remove };
}
