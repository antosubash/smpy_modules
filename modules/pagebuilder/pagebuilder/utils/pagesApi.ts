/** Page, layout, and revision calls against the pagebuilder admin API. */

import { request } from './request';
import type {
  LayoutDetail,
  LayoutRevisionRead,
  LayoutUpdate,
  LocalesResponse,
  PageDetail,
  PageRead,
  PageRevisionRead,
  PageTranslationPayload,
  PageWritePayload,
  RevisionDiff,
  ScheduleRequest,
} from './types';

export const createPage = (
  data: PageWritePayload & { title: string; slug: string; locale?: string },
) => request<PageDetail>('/pages', { method: 'POST', body: JSON.stringify(data) });

/** Pages waiting out the retention window. */
export const listTrash = () => request<{ items: PageRead[] }>('/pages/trash');

/** Bring a trashed page back. It returns as a draft, never straight to live. */
export const restorePage = (id: number) =>
  request<PageDetail>(`/pages/${id}/restore`, { method: 'POST' });

/** Remove a trashed page for good. Not reversible. */
export const purgePage = (id: number) => request<void>(`/pages/${id}/purge`, { method: 'DELETE' });

/** Pages offered as starting points by the New page dialog. */
export const listTemplates = (signal?: AbortSignal) =>
  request<{ items: PageRead[] }>('/pages/templates', { signal });

/** Every page, for the "copy a page" and parent selects.
 *
 * `locale` narrows to one language — what the parent select wants, since
 * breadcrumbs must not cross languages. */
export const listPages = (signal?: AbortSignal, locale?: string) =>
  request<{ items: PageRead[] }>(
    locale ? `/pages?locale=${encodeURIComponent(locale)}` : '/pages',
    {
      signal,
    },
  );

/** Which languages a page may be authored in. */
export const listLocales = (signal?: AbortSignal) =>
  request<LocalesResponse>('/locales', { signal });

/** Start this page's counterpart in another language. Returns the new page. */
export const createTranslation = (id: number, body: PageTranslationPayload) =>
  request<PageDetail>(`/pages/${id}/translations`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const savePage = (id: number, data: PageWritePayload) =>
  request<PageDetail>(`/pages/${id}`, { method: 'PUT', body: JSON.stringify(data) });

export const deletePage = (id: number) => request<void>(`/pages/${id}`, { method: 'DELETE' });

function noteBody(note?: string | null): BodyInit | undefined {
  return note ? JSON.stringify({ note }) : undefined;
}

export const publishPage = (id: number, note?: string | null) =>
  request<PageRead>(`/pages/${id}/publish`, {
    method: 'POST',
    body: noteBody(note),
  });

export const unpublishPage = (id: number, note?: string | null) =>
  request<PageRead>(`/pages/${id}/unpublish`, {
    method: 'POST',
    body: noteBody(note),
  });

export const submitPage = (id: number, note?: string | null) =>
  request<PageRead>(`/pages/${id}/submit`, {
    method: 'POST',
    body: noteBody(note),
  });

export const approvePage = (id: number, note?: string | null) =>
  request<PageRead>(`/pages/${id}/approve`, {
    method: 'POST',
    body: noteBody(note),
  });

export const rejectPage = (id: number, note: string) =>
  request<PageRead>(`/pages/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  });

export const listPendingPages = () => request<{ items: PageRead[] }>('/pages/pending');

export const schedulePage = (id: number, body: ScheduleRequest) =>
  request<PageRead>(`/pages/${id}/schedule`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const listRevisions = (id: number) =>
  request<{ items: PageRevisionRead[] }>(`/pages/${id}/revisions`);

export const restoreRevision = (pageId: number, revisionId: number) =>
  request<PageDetail>(`/pages/${pageId}/revisions/${revisionId}/restore`, {
    method: 'POST',
  });

export const diffRevisions = (pageId: number, beforeId: number, afterId: number) =>
  request<RevisionDiff>(`/pages/${pageId}/revisions/${beforeId}/diff/${afterId}`);

export const getLayout = () => request<LayoutDetail>('/layout');

export const saveLayout = (body: LayoutUpdate) =>
  request<LayoutDetail>('/layout', {
    method: 'PUT',
    body: JSON.stringify(body),
  });

export const listLayoutRevisions = () =>
  request<{ items: LayoutRevisionRead[] }>('/layout/revisions');

export const restoreLayoutRevision = (revisionId: number) =>
  request<LayoutDetail>(`/layout/revisions/${revisionId}/restore`, {
    method: 'POST',
  });
