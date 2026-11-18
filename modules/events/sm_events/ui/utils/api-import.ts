/**
 * The import screen's calls and the words for every code the server can answer with.
 * Everything that came from the uploaded file (titles, identifiers) is data: components render it
 * as text and never interpret it.
 */

import { send } from './api';
import { keys, translate as t } from './i18n';

export type ImportStatus =
  | 'uploaded'
  | 'parsing'
  | 'staged'
  | 'queued'
  | 'running'
  | 'done'
  | 'failed';

export type ImportRow = {
  id: number;
  calendar: { id: string; name: string };
  status: ImportStatus;
  filename: string;
  size_bytes: number;
  total: number;
  counts: Record<string, number>;
  reasons: Record<string, number>;
  dropped: Record<string, number>;
  created: number;
  updated: number;
  unchanged: number;
  skipped: number;
  failed: number;
  processed: number;
  error_code: string | null;
  publish: boolean;
  created_at: string;
  finished_at: string | null;
};

export type ImportItem = {
  seq: number;
  uid: string;
  verdict: 'new' | 'update' | 'skip';
  reason: string | null;
  notes: string[];
  title: string;
  starts_at: string | null;
  timezone: string | null;
  local_start: string | null;
  all_day: boolean;
  recurring: boolean;
  outcome: string | null;
  outcome_code: string | null;
  event_id: string | null;
};

export type ItemPage = { items: ImportItem[]; total: number; page: number; page_size: number };

/** States a worker still owns: the screen polls while an import is in one. */
export const ACTIVE: readonly ImportStatus[] = ['uploaded', 'parsing', 'queued', 'running'];
export const POLL_MS = 1000;

/** Why an item was skipped or could not be written (``constants/imports``' reason codes). */
export const SKIP_REASONS = [
  'unknown_timezone',
  'invalid_times',
  'invalid_local_time',
  'too_many_properties',
  'too_many_parameters',
  'event_too_large',
  'too_many_attendees',
  'end_before_start',
  'duration_too_long',
  'unsupported_rule',
  'too_many_overrides',
  'override_without_master',
  'uid_too_long',
  'uid_invalid',
  'uid_in_trash',
  'duplicate_uid',
  'changed_since_preview',
  'publish_required',
  'write_failed',
  'forbidden',
  'private_kept',
  'invalid_event',
] as const;
/** What was adjusted on the way in, for an item that is imported. */
export const NOTES = [
  'floating_time',
  'kept_utc',
  'default_duration',
  'shifted_local_time',
  'start_adjusted',
  'exdate_ignored',
  'override_fields_dropped',
  'override_dropped',
  'category_dropped',
  'kept_draft_private',
  'untitled',
  'uid_generated',
  'description_truncated',
] as const;
export const REASON_CODES: readonly string[] = [...SKIP_REASONS, ...NOTES];

const lookup = (table: object, code: string): string | undefined =>
  (table as Record<string, string | undefined>)[code];

/** A reason or note in words; a code this screen has no words for is a generic line, never the code. */
export function reasonText(code: string): string {
  const key = lookup(keys.events.import.reasons, code);
  return key ? t(key) : t(keys.events.errors.generic);
}

export function failureText(code: string | null): string {
  const key = code ? lookup(keys.events.import.failure, code) : undefined;
  return t(key ?? keys.events.import.failure.import_failed);
}

/** "attendees 3": the dropped properties as the report names them. */
export function droppedText(name: string): string {
  return t(lookup(keys.events.import.dropped, name) ?? keys.events.import.dropped.other);
}

const BASE = '/api/events/imports';
const query = (params: Record<string, string | number | undefined>) => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined) qs.set(k, String(v));
  const text = qs.toString();
  return text ? `?${text}` : '';
};

export const uploadImport = (calendarId: string, file: File): Promise<ImportRow> => {
  const form = new FormData();
  form.append('calendar_id', calendarId);
  form.append('file', file, file.name);
  return send(BASE, { method: 'POST', body: form });
};
export const getImport = (id: number, signal?: AbortSignal): Promise<ImportRow> =>
  send(`${BASE}/${id}`, { signal });
export const listItems = (
  id: number,
  params: { verdict?: string; outcome?: string; page?: number },
  signal?: AbortSignal,
): Promise<ItemPage> =>
  send(`${BASE}/${id}/items${query({ ...params, page_size: 50 })}`, { signal });
export const applyImport = (id: number, publish: boolean): Promise<ImportRow> =>
  send(`${BASE}/${id}/apply`, { method: 'POST', json: { publish } });
export const discardImport = (id: number): Promise<void> =>
  send(`${BASE}/${id}`, { method: 'DELETE' });
