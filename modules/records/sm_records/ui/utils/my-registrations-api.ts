/** The caller's own registrations: `GET` lists, `POST .../cancel` cancels one and returns the rest. */
import { request } from './api';

export type MineItem = {
  uuid: string;
  type_key: string;
  status: 'pending' | 'registered';
  event_id: string;
  occurrence_key: string;
  title: string;
  when_text: string | null;
  page_path: string | null;
  starts_at: string | null;
  /** `false`: events no longer answers for it; shown as unavailable, with no cancel. */
  available: boolean;
};
export type Mine = { verified: boolean; items: MineItem[] };

export const listMine = (): Promise<Mine> => request('/registrations/mine');
export const cancelMine = (uuid: string): Promise<Mine> =>
  request(`/registrations/mine/${encodeURIComponent(uuid)}/cancel`, { method: 'POST' });
