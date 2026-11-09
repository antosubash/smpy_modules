/** Typed client for `/api/newsletter`. Failures throw `HttpError` (see http.ts);
 *  screens show `errorMessage(e, t)`. */

import { read, send, write } from './http';
import type {
  Block,
  CampaignDetail,
  CampaignPage,
  CardHit,
  CardKind,
  CardSnapshot,
  Estimate,
  Lift,
  LiftPage,
  ListField,
  MediaHit,
  Preview,
  Progress,
  Report,
  Rule,
  Segment,
  SegmentBody,
  SettingsOut,
  SettingsSaved,
  SettingsUpdate,
  Subscriber,
  SubscriberDetail,
  SubscriberPage,
  SubscriberSearch,
  Suppression,
  SuppressionPage,
  TestSendResult,
} from './types';

export { errorMessage } from './http';

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(name, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

export const api = {
  listCampaigns: (p: { q?: string; status?: string; offset?: number }, signal?: AbortSignal) =>
    read<CampaignPage>(`/campaigns${query(p)}`, signal),
  createCampaign: (b: { name: string; list_type_key: string }) =>
    send<CampaignDetail>('/campaigns', 'POST', b),
  getCampaign: (id: number) => read<CampaignDetail>(`/campaigns/${id}`),
  patchCampaign: (id: number, b: Partial<CampaignDetail> & { expected_revision: number }) =>
    send<CampaignDetail>(`/campaigns/${id}`, 'PATCH', b),
  deleteCampaign: async (id: number): Promise<void> => {
    await write(`/campaigns/${id}`, 'DELETE');
  },
  lists: () => read<string[]>('/lists'),
  searchCards: (kind: CardKind, q: string, signal?: AbortSignal) =>
    read<CardHit[]>(`/cards/${kind}s${query({ q })}`, signal),
  snapshot: (kind: CardKind, source_id: number) =>
    send<CardSnapshot>('/cards/snapshot', 'POST', { kind, source_id }),
  refreshCard: (id: number, block_id: string, expected_revision: number) =>
    send<CampaignDetail>(`/campaigns/${id}/cards/refresh`, 'POST', { block_id, expected_revision }),
  searchMedia: (q: string, signal?: AbortSignal) =>
    read<MediaHit[]>(`/media${query({ q })}`, signal),
  preview: (id: number) => read<Preview>(`/campaigns/${id}/preview`),
  previewUnsaved: (b: { subject: string; preheader: string; body: Block[] }) =>
    send<Preview>('/preview', 'POST', b),
  testSend: (id: number, recipients: string[]) =>
    send<{ results: TestSendResult[] }>(`/campaigns/${id}/test-send`, 'POST', { recipients }),
  sendCampaign: (id: number, b: { expected_revision: number; scheduled_at: string | null }) =>
    send<CampaignDetail>(`/campaigns/${id}/send`, 'POST', b),
  unscheduleCampaign: (id: number, expected_revision: number) =>
    send<CampaignDetail>(`/campaigns/${id}/unschedule`, 'POST', { expected_revision }),
  pauseCampaign: (id: number) => send<CampaignDetail>(`/campaigns/${id}/pause`, 'POST'),
  resumeCampaign: (id: number) => send<CampaignDetail>(`/campaigns/${id}/resume`, 'POST'),
  cancelCampaign: (id: number) => send<CampaignDetail>(`/campaigns/${id}/cancel`, 'POST'),
  progress: (id: number, signal?: AbortSignal) =>
    read<Progress>(`/campaigns/${id}/progress`, signal),
  report: (id: number, signal?: AbortSignal) => read<Report>(`/campaigns/${id}/report`, signal),
  estimate: (id: number, at: string | null) =>
    read<Estimate>(`/campaigns/${id}/estimate${query({ at: at ?? undefined })}`),
  getSettings: () => read<SettingsOut>('/settings'),
  putSettings: (b: SettingsUpdate) => send<SettingsSaved>('/settings', 'PUT', b),
  putPassword: (password: string) =>
    send<{ has_password: boolean }>('/settings/smtp-password', 'PUT', { password }),
  listFields: (key: string) => read<ListField[]>(`/lists/${encodeURIComponent(key)}/fields`),
  audienceCount: (key: string, audience: string, signal?: AbortSignal) =>
    read<{ count: number }>(
      `/lists/${encodeURIComponent(key)}/audience-count${query({ audience })}`,
      signal,
    ),
  listSegments: (list?: string) => read<Segment[]>(`/segments${query({ list_type_key: list })}`),
  getSegment: (id: number) => read<Segment>(`/segments/${id}`),
  createSegment: (b: SegmentBody) => send<Segment>('/segments', 'POST', b),
  patchSegment: (id: number, b: { name?: string; rules?: Rule[] }) =>
    send<Segment>(`/segments/${id}`, 'PATCH', b),
  deleteSegment: async (id: number): Promise<void> => {
    await write(`/segments/${id}`, 'DELETE');
  },
  previewSegment: (b: { list_type_key: string; rules: Rule[] }, signal?: AbortSignal) =>
    send<{ count: number }>('/segments/preview', 'POST', b, signal),
  searchSubscribers: (key: string, body: SubscriberSearch, signal?: AbortSignal) =>
    send<SubscriberPage>(
      `/lists/${encodeURIComponent(key)}/subscribers/search`,
      'POST',
      body,
      signal,
    ),
  getSubscriber: (key: string, uuid: string) =>
    read<SubscriberDetail>(`/lists/${encodeURIComponent(key)}/subscribers/${uuid}`),
  tagSubscriber: (key: string, uuid: string, b: { add: string[]; remove: string[] }) =>
    send<Subscriber>(`/lists/${encodeURIComponent(key)}/subscribers/${uuid}/tags`, 'POST', b),
  unsubscribeSubscriber: (key: string, uuid: string) =>
    send<Subscriber>(
      `/lists/${encodeURIComponent(key)}/subscribers/${uuid}/unsubscribe`,
      'POST',
      {},
    ),
  listSuppressions: (
    p: { reason?: string; offset?: number; limit?: number },
    signal?: AbortSignal,
  ) => read<SuppressionPage>(`/suppressions${query(p)}`, signal),
  lookupSuppressions: (email: string) =>
    send<Suppression[]>('/suppressions/lookup', 'POST', { email }),
  liftSuppression: (id: number, b: { version: string; email: string; note: string }) =>
    send<Lift>(`/suppressions/${id}/lift`, 'POST', b),
  listLifts: (p: { offset?: number; limit?: number }, signal?: AbortSignal) =>
    read<LiftPage>(`/suppressions/lifts${query(p)}`, signal),
};
