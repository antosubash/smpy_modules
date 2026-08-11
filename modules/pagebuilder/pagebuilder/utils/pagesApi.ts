/** Page, layout, and revision calls against the pagebuilder admin API. */

import { request } from './request';
import type {
  LayoutDetail,
  LayoutRevisionRead,
  LayoutUpdate,
  PageDetail,
  PageRead,
  PageRevisionRead,
  PageWritePayload,
  RevisionDiff,
  ScheduleRequest,
} from './types';

export const createPage = (data: PageWritePayload & { title: string; slug: string }) =>
  request<PageDetail>('/pages', { method: 'POST', body: JSON.stringify(data) });

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
