/** The extension registry's API: the installed plugin sources, and enabling them on a calendar. */
import { send } from './api';
import type { Calendar } from './types';

export type SourceInfo = {
  id: string;
  label_key: string;
  color: string | null;
  icon: string | null;
  public: boolean;
  has_settings: boolean;
  settings_schema: Record<string, unknown> | null;
};
export type SourceEntryInput = { id: string; settings: Record<string, unknown> };

export const listSources = (signal?: AbortSignal) =>
  send<SourceInfo[]>('/api/events/sources', { signal });

/** `expected` is the `sources_version` of the calendar as it was read; another write since
 *  is a 409 `stale`. */
export const putCalendarSources = (id: string, sources: SourceEntryInput[], expected: string) =>
  send<Calendar>(`/api/events/calendars/${id}/sources`, {
    method: 'PUT',
    json: { sources, expected },
  });
