/** Typed client for `/api/newsletter`. Failures throw `HttpError` (see http.ts);
 *  screens show `errorMessage(e, t)`. */

import { read, write } from './http';
import type {
  Block,
  CampaignDetail,
  CampaignPage,
  CardHit,
  CardKind,
  CardSnapshot,
  MediaHit,
  Preview,
  SettingsOut,
  SettingsSaved,
  SettingsUpdate,
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

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  return (await write<T>(path, method, body)) as T;
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
  getSettings: () => read<SettingsOut>('/settings'),
  putSettings: (b: SettingsUpdate) => send<SettingsSaved>('/settings', 'PUT', b),
  putPassword: (password: string) =>
    send<{ has_password: boolean }>('/settings/smtp-password', 'PUT', { password }),
};
