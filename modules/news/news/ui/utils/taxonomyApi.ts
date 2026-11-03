/** Client for the category and tag management API.
 *
 * These live under `/taxonomy` rather than beside the public `/categories`
 * listing because every GET under that path is anonymously readable — see the
 * endpoint module for the full reason.
 */

import { read, write } from './http';

export interface CategoryRead {
  /** 0 for the system Uncategorised bucket and for a category that exists only
   *  as free text on articles. Neither can be renamed or reordered yet. */
  id: number;
  name: string;
  slug: string;
  position: number;
  article_count: number;
  is_system: boolean;
}

export interface TagRead {
  id: number;
  name: string;
  slug: string;
  article_count: number;
}

/** A category the screen may act on: it has a row, so it has an id. */
export function isManaged(category: CategoryRead): boolean {
  return category.id > 0 && !category.is_system;
}

export const listManagedCategories = (signal?: AbortSignal) =>
  read<{ items: CategoryRead[] }>('/taxonomy/categories', signal);

export const createCategory = (data: { name: string; slug?: string }) =>
  write<CategoryRead>('/taxonomy/categories', 'POST', data);

export const updateCategory = (id: number, data: { name?: string; slug?: string }) =>
  write<CategoryRead>(`/taxonomy/categories/${id}`, 'PUT', data);

export const reorderCategories = (orderedIds: number[]) =>
  write<null>('/taxonomy/categories/reorder', 'POST', { ordered_ids: orderedIds });

/** Delete, moving the articles. `reassignTo` is a category *name*; empty means
 *  Uncategorised. No article is ever deleted. */
export const deleteCategory = (id: number, reassignTo = '') =>
  write<{ reassigned: number }>(
    `/taxonomy/categories/${id}?reassign_to=${encodeURIComponent(reassignTo)}`,
    'DELETE',
  );

export const listTags = (signal?: AbortSignal) =>
  read<{ items: TagRead[] }>('/taxonomy/tags', signal);

export const createTag = (name: string) => write<TagRead>('/taxonomy/tags', 'POST', { name });

export const renameTag = (id: number, name: string) =>
  write<TagRead>(`/taxonomy/tags/${id}`, 'PUT', { name });

/** Fold `sourceId` into `id`; the source row is removed. */
export const mergeTags = (id: number, sourceId: number) =>
  write<{ moved: number }>(`/taxonomy/tags/${id}/merge`, 'POST', { source_id: sourceId });

export const deleteTag = (id: number) => write<null>(`/taxonomy/tags/${id}`, 'DELETE');

export const listArticleTags = (articleId: number, signal?: AbortSignal) =>
  read<string[]>(`/articles/${articleId}/tags`, signal);

export const setArticleTags = (articleId: number, tags: string[]) =>
  write<string[]>(`/articles/${articleId}/tags`, 'PUT', { tags });
