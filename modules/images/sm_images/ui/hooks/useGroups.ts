import { useCallback } from 'react';

import { createGroup, deleteGroup, listGroups, updateGroup } from '../utils/api-groups';
import type { GroupItem } from '../utils/types';
import { type CursorList, useCursorList } from './useCursorList';

type Fields = { key: string; name: string | null };

export type Groups = CursorList<GroupItem> & {
  create: (value: Fields) => Promise<void>;
  edit: (group: GroupItem, value: Fields) => Promise<void>;
  remove: (group: GroupItem) => Promise<void>;
};

/** A collection's groups, key-ordered and paged, with their first members. Every
 *  change re-reads the list, so counts and order are the server's. */
export function useGroups(collectionId: string): Groups {
  const list = useCursorList(collectionId, (cursor) => listGroups(collectionId, cursor));
  const { reload } = list;
  const create = useCallback(
    async (value: Fields) => {
      await createGroup(collectionId, value);
      await reload();
    },
    [collectionId, reload],
  );
  const edit = useCallback(
    async (group: GroupItem, value: Fields) => {
      await updateGroup(group.id, value);
      await reload();
    },
    [reload],
  );
  const remove = useCallback(
    async (group: GroupItem) => {
      await deleteGroup(group.id);
      await reload();
    },
    [reload],
  );
  return { ...list, create, edit, remove };
}
