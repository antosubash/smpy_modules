/** The events API: every call goes through `send`, so a failure is an `ApiError`. */
import { send } from './api';
import type {
  EventCreate,
  EventDetail,
  EventPage,
  EventPatch,
  EventQuery,
  Occurrence,
  OccurrenceQuery,
  OverrideInput,
  OverrideResult,
  Preview,
  PreviewInput,
  Revision,
  RevisionDetail,
  WorkflowAction,
  WorkflowBody,
} from './types-events';

const EVENTS = '/api/events/events';

function query(params: object): string {
  const qs = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '' || value === false) continue;
    if (Array.isArray(value)) for (const item of value) qs.append(name, String(item));
    else qs.set(name, String(value));
  }
  const text = qs.toString();
  return text ? `?${text}` : '';
}

export const listEvents = (params: EventQuery, signal?: AbortSignal) =>
  send<EventPage>(`${EVENTS}${query(params)}`, { signal });
export const getEvent = (id: string, locale?: string, signal?: AbortSignal) =>
  send<EventDetail>(`${EVENTS}/${id}${query({ locale })}`, { signal });
export const createEvent = (body: EventCreate) =>
  send<EventDetail>(EVENTS, { method: 'POST', json: body });
export const updateEvent = (id: string, body: EventPatch) =>
  send<EventDetail>(`${EVENTS}/${id}`, { method: 'PATCH', json: body });
export const trashEvent = (id: string, revision: number) =>
  send<void>(`${EVENTS}/${id}?expected_revision=${revision}`, { method: 'DELETE' });
export const restoreEvent = (id: string, revision: number) =>
  send<EventDetail>(`${EVENTS}/${id}/restore`, {
    method: 'POST',
    json: { expected_revision: revision },
  });
export const transition = (id: string, action: WorkflowAction, body: WorkflowBody) =>
  send<EventDetail>(`${EVENTS}/${id}/${action}`, { method: 'POST', json: body });
export const listRevisions = (id: string, signal?: AbortSignal) =>
  send<Revision[]>(`${EVENTS}/${id}/revisions`, { signal });
export const getRevision = (id: string, number: number, signal?: AbortSignal) =>
  send<RevisionDetail>(`${EVENTS}/${id}/revisions/${number}`, { signal });
export const setOverride = (id: string, body: OverrideInput) =>
  send<OverrideResult>(`${EVENTS}/${id}/overrides`, { method: 'POST', json: body });
export const clearOverride = (id: string, overrideId: number, revision: number) =>
  send<void>(`${EVENTS}/${id}/overrides/${overrideId}?expected_revision=${revision}`, {
    method: 'DELETE',
  });
export const previewRecurrence = (body: PreviewInput, signal?: AbortSignal) =>
  send<Preview>('/api/events/recurrence/preview', { method: 'POST', json: body, signal });
export const listOccurrences = (params: OccurrenceQuery, signal?: AbortSignal) =>
  send<{ items: Occurrence[]; truncated: boolean }>(`/api/events/occurrences${query(params)}`, {
    signal,
  });
