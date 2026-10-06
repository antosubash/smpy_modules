import { useCallback, useRef, useState } from 'react';

import {
  type CategoryRead,
  createCategory,
  createTag,
  deleteCategory,
  listManagedCategories,
  listTags,
  mergeTags as mergeTagsRequest,
  reorderCategories,
  type TagRead,
  updateCategory,
} from '../utils/taxonomyApi';

/** Loads and mutates both taxonomies for the categories screen.
 *
 * Every mutation re-reads both lists rather than patching state in place. That
 * is not laziness: renaming a category rewrites every article carrying the old
 * name, and merging tags moves links across two rows, so the counts on screen
 * after any write are not derivable from the response to that write.
 */
export function useTaxonomy() {
  const [categories, setCategories] = useState<CategoryRead[]>([]);
  const [tags, setTags] = useState<TagRead[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Only the newest load may write state. Reordering fires a refresh while a
  // rename's refresh may still be in flight, and the slower one landing last
  // would repaint the list in the order it had before the drag.
  const latest = useRef(0);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const request = ++latest.current;
    try {
      const [categoryList, tagList] = await Promise.all([
        listManagedCategories(signal),
        listTags(signal),
      ]);
      if (request !== latest.current) return;
      setCategories(categoryList.items);
      setTags(tagList.items);
      // A load that worked clears a banner left by one that did not.
      setError(null);
    } catch (e) {
      if (signal?.aborted || request !== latest.current) return;
      setError((e as Error).message);
    }
  }, []);

  /** Run a write, then re-read. Errors surface in the banner, not as a throw —
   *  except for the dialogs, which need the rejection to stay open on failure. */
  const run = useCallback(
    async (work: () => Promise<unknown>) => {
      setBusy(true);
      setError(null);
      try {
        await work();
        await refresh();
      } catch (e) {
        setError((e as Error).message);
        throw e;
      } finally {
        setBusy(false);
      }
    },
    [refresh],
  );

  /** Resolves to whether the rename was written. The failure is already in
   *  the banner; the row uses the result to stay in edit mode, so a refused
   *  name (a duplicate, say) is still there to correct rather than discarded. */
  const saveCategory = useCallback(
    async (id: number, name: string, slug: string) => {
      try {
        await run(() => updateCategory(id, { name, slug }));
        return true;
      } catch {
        return false;
      }
    },
    [run],
  );

  const addCategory = useCallback((name: string) => run(() => createCategory({ name })), [run]);

  const removeCategory = useCallback(
    (id: number, reassignTo: string) => run(() => deleteCategory(id, reassignTo)),
    [run],
  );

  const persistOrder = useCallback(
    (orderedIds: number[]) => run(() => reorderCategories(orderedIds)),
    [run],
  );

  const addTag = useCallback((name: string) => run(() => createTag(name)), [run]);

  const mergeTags = useCallback(
    (targetId: number, sourceId: number) => run(() => mergeTagsRequest(targetId, sourceId)),
    [run],
  );

  return {
    categories,
    tags,
    busy,
    error,
    refresh,
    saveCategory,
    addCategory,
    removeCategory,
    persistOrder,
    addTag,
    mergeTags,
  };
}
