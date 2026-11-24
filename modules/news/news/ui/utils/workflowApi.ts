import { write } from './http';
import type { ArticleDetail, ArticleRead } from './types';

export const restoreArticleRevision = (
  id: number,
  revisionId: number,
  expected_updated_at?: string | null,
) =>
  write<ArticleDetail>(`/articles/${id}/revisions/${revisionId}/restore`, 'POST', {
    expected_updated_at,
  });

/** Snapshot the draft and serve it. Requires `news.publish`. */
export const publishArticle = (id: number, expected_updated_at?: string | null) =>
  write<ArticleRead>(`/articles/${id}/publish`, 'POST', { expected_updated_at });

/** Take it off the public site, keeping the draft. Requires `news.publish`. */
export const unpublishArticle = (id: number, expected_updated_at?: string | null) =>
  write<ArticleRead>(`/articles/${id}/unpublish`, 'POST', { expected_updated_at });

/** Hand a draft to a reviewer. `news.edit` alone — it is what an author does
 *  when they cannot publish. */
export const submitArticle = (id: number, expected_updated_at?: string | null) =>
  write<ArticleRead>(`/articles/${id}/submit`, 'POST', { expected_updated_at });

/** Approve a submission — which also publishes it. One action, because a
 *  reviewer who has to approve and then publish separately eventually forgets
 *  the second half. Requires `news.publish`. */
export const approveArticle = (id: number, expected_updated_at?: string | null) =>
  write<ArticleRead>(`/articles/${id}/approve`, 'POST', { expected_updated_at });

/** Send a submission back, with a reason the author sees on the canvas. */
export const rejectArticle = (id: number, note: string, expected_updated_at?: string | null) =>
  write<ArticleRead>(`/articles/${id}/reject`, 'POST', { note, expected_updated_at });

/** Move to the trash. Answers 204: there is no visible article to return. */
export const trashArticle = (id: number) => write<null>(`/articles/${id}/trash`, 'POST', {});

/** Remove for good, with its redirects. Requires `news.publish`. */
export const purgeArticle = (id: number) =>
  write<null>(`/articles/${id}/purge`, 'DELETE', undefined);

export const restoreArticle = (id: number) =>
  write<ArticleRead>(`/articles/${id}/restore`, 'POST', {});
