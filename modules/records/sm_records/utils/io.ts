/**
 * The import/export half of the records API, kept out of `utils/api.ts`.
 *
 * Not only for the 300-line cap: `api.ts`'s `request()` pins
 * `Content-Type: application/json` on every call, and an import is a
 * `multipart/form-data` upload whose boundary the browser has to choose. A
 * call that went through `request()` would have to unset a header that
 * helper exists to set.
 *
 * Export is a plain `<a href>` rather than a `fetch`: the response carries
 * `Content-Disposition: attachment`, so the browser saves it, streaming, with
 * no blob buffered in the tab. Fetching it to build an object URL would undo
 * the one property the endpoint was written for.
 */

import type { FieldDef } from './types';

// The rest of this module types `t` loosely for the same reason
// `pages/RecordList.tsx` does — see that file's comment.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

export type ImportRowError = {
  row: number;
  uuid?: string | null;
  field?: string | null;
  message: string;
};

export type ImportReport = {
  dry_run: boolean;
  mode: string;
  total: number;
  created: number;
  updated: number;
  skipped: number;
  failed: number;
  errors: ImportRowError[];
  errors_truncated: boolean;
  duration_ms: number;
};

const BASE = '/api/records';

/** The download URL for one type, carrying the list screen's own
 *  `filter`/`sort`/`trashed` so "Export" means "export what I am looking at"
 *  rather than "export everything, whatever the screen says". */
export function exportUrl(typeKey: string, format: 'json' | 'csv', search?: string): string {
  const params = new URLSearchParams(search ?? '');
  params.delete('page');
  params.set('format', format);
  return `${BASE}/types/${encodeURIComponent(typeKey)}/records/export?${params.toString()}`;
}

export type ImportOptions = {
  dryRun?: boolean;
  mode?: 'upsert' | 'create' | 'update';
  onError?: 'abort' | 'skip';
  /** `'uuid'` | `'slug'` | a unique field's key — mirrors the API's
   *  `match_by` (`services/_import_match.py`). */
  matchBy?: string;
  /** Overwrite a record whose stored version the file does not carry
   *  (`services/_import_rows.py`'s "no version" refusal). */
  force?: boolean;
};

/** The subset of `RecordImportOptions`' `ImportOptionsValue` this file reads
 *  — named structurally instead of imported from `components/`, so the API
 *  layer doesn't reach up into a component for a type. */
export type ImportOptionsSummaryInput = {
  mode: string;
  matchBy: string;
  force: boolean;
};

/** `match_by`'s wire value, as a label a person picked it from — mirrors the
 *  three options `RecordImportOptions` renders (R23: the select itself no
 *  longer shows `uuid`/`slug` raw). */
function matchByLabel(t: Translate, matchBy: string, fields: FieldDef[]): string {
  if (matchBy === 'uuid') {
    return t('records.io.match_by_uuid', { defaultValue: 'Record ID (uuid)' });
  }
  if (matchBy === 'slug') {
    return t('records.io.match_by_slug', { defaultValue: 'Slug' });
  }
  const field = fields.find((candidate) => candidate.key === matchBy);
  return field ? `${field.label} (${field.key})` : matchBy;
}

/** The compact "what will happen" line `RecordIoMenu`'s dialog shows next to
 *  the picked file (R21) — the options popover used to close before Apply
 *  and take this context with it, leaving the confirm step restating
 *  nothing. Kept here rather than in the component so `io.test.ts` can cover
 *  every branch without mounting anything. */
export function importOptionsSummary(
  t: Translate,
  options: ImportOptionsSummaryInput,
  fields: FieldDef[],
): string {
  const modeText =
    options.mode === 'create'
      ? t('records.io.mode_create', { defaultValue: 'Create only' })
      : options.mode === 'update'
        ? t('records.io.mode_update', { defaultValue: 'Update only' })
        : t('records.io.mode_upsert', { defaultValue: 'Create or update (upsert)' });
  const forceText = options.force
    ? t('records.io.summary_force_on', { defaultValue: 'overwrite unversioned rows: on' })
    : t('records.io.summary_force_off', { defaultValue: 'overwrite unversioned rows: off' });
  return [
    modeText,
    t('records.io.summary_match_by', {
      label: matchByLabel(t, options.matchBy, fields),
      defaultValue: 'match by {label}',
    }),
    forceText,
  ].join(' · ');
}

/** POST one file and return the report.
 *
 * A refused run (`on_error=abort` with bad rows) answers 422 with the same
 * report under `report` — it is returned rather than thrown, because the
 * report *is* the answer the operator asked for and a thrown error would
 * make the caller reconstruct it from a message. Anything else that fails is
 * thrown with the server's `detail`.
 */
export async function importRecords(
  typeKey: string,
  file: File,
  options: ImportOptions = {},
): Promise<ImportReport> {
  const body = new FormData();
  body.append('file', file);
  body.append('dry_run', String(options.dryRun ?? true));
  if (options.mode) body.append('mode', options.mode);
  if (options.onError) body.append('on_error', options.onError);
  if (options.matchBy) body.append('match_by', options.matchBy);
  if (options.force) body.append('force', 'true');

  const response = await fetch(`${BASE}/types/${encodeURIComponent(typeKey)}/records/import`, {
    method: 'POST',
    credentials: 'same-origin',
    body,
  });
  const text = await response.text().catch(() => '');
  let parsed: { report?: ImportReport; detail?: string } | ImportReport | null = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }
  if (response.ok) {
    // An empty or unparseable 2xx body (L9) would otherwise hand the caller
    // a `null` typed as `ImportReport`, which `RecordIoMenu` dereferences
    // (`result.failed`) — a `TypeError` surfacing as a raw, unhelpful toast
    // instead of a message that says what actually went wrong.
    if (parsed === null) {
      throw new Error(`Import response was empty or unreadable (${response.status})`);
    }
    return parsed as ImportReport;
  }
  const report = (parsed as { report?: ImportReport } | null)?.report;
  if (report) return report;
  const detail = (parsed as { detail?: string } | null)?.detail;
  throw new Error(detail || `Import failed (${response.status})`);
}
