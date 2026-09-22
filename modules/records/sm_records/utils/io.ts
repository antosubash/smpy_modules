/**
 * The import/export half of the records API, kept out of `utils/api.ts`.
 *
 * Not only for the 300-line cap: `api.ts`'s `request()` pins
 * `Content-Type: application/json` on every call, and an import is a
 * `multipart/form-data` upload whose boundary the browser has to choose. A
 * call that went through `request()` would have to unset a header that
 * helper exists to set.
 *
 * What it does *not* get to skip is what `request()` does about the
 * connection rather than the payload (R9): an expired session redirects to
 * the sign-in page with `next` pointing back here, and a `fetch` that
 * rejects outright becomes the module's own offline `ApiError` instead of a
 * raw `TypeError: Failed to fetch`. Both live in `utils/api-net.ts` for
 * exactly this reuse.
 *
 * Export is a plain `<a href>` rather than a `fetch`: the response carries
 * `Content-Disposition: attachment`, so the browser saves it, streaming, with
 * no blob buffered in the tab. Fetching it to build an object URL would undo
 * the one property the endpoint was written for.
 */

import { ApiError, handleUnauthorized, messageFor, offlineError, parseBody } from './api-net';
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

/** `RecordsSettings.max_import_bytes`'s own default (`settings.py`, 50 MiB).
 *
 * The *effective* limit travels as a prop (`views.py::record_list` sends
 * `max_import_bytes`, since an operator may have changed it); this is the
 * fallback for a caller that has no prop to read, and it is pinned against
 * the Python default by `tests/test_reserved_keys_sync.py`. Before R9 the
 * whole file was posted and the server answered 413 *after* the upload —
 * 50 MB uphill on a domestic connection to be told the limit exists. */
export const DEFAULT_MAX_IMPORT_BYTES = 52428800;

/** Whether this file is small enough to be worth sending. */
export function importFileTooLarge(size: number, limit: number): boolean {
  return size > limit;
}

/** The limit as a person reads it — one decimal, MB, for the dialog's own
 *  sentence and for the refusal. */
export function formatImportLimit(limit: number): string {
  return `${Math.round((limit / (1024 * 1024)) * 10) / 10} MB`;
}

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

  let response: Response;
  try {
    response = await fetch(`${BASE}/types/${encodeURIComponent(typeKey)}/records/import`, {
      method: 'POST',
      credentials: 'same-origin',
      body,
    });
  } catch {
    // A dropped connection mid-upload — the one failure most likely on a
    // request this size.
    throw offlineError();
  }
  if (response.status === 401) {
    handleUnauthorized();
    throw new ApiError(401, await parseBody(response), messageFor(401, response.statusText, null));
  }
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

/** Whether Apply should be offered at all, and why not when it shouldn't be.
 *
 * `null` means Apply can run. A non-`dry_run` report is never blocked here —
 * it already happened. A dry run with `failed === 0` is never blocked
 * either. The one case this names is a dry run that found failing rows
 * *and* the operator is still on `on_error: 'abort'`: the server would
 * refuse the whole write, so offering an enabled Apply that always 422s is
 * worse than not offering one, but removing the button with no explanation
 * (U3) left the dialog looking like the feature had vanished. Naming the
 * `on_error: 'skip'` escape hatch here — rather than just disabling — is
 * what lets an operator get unstuck without hunting through Import options.
 */
export function importApplyBlockedReason(
  t: Translate,
  report: Pick<ImportReport, 'dry_run' | 'failed' | 'total'>,
  onError: 'abort' | 'skip',
): string | null {
  if (!report.dry_run || report.failed === 0) return null;
  if (onError === 'skip') return null;
  // U10: "N of M rows" declines by M (the total), while "Fix it/them" declines
  // by N (the failed rows) — two nouns, two plural forms, so two keys.
  const sentence = t('records.io.apply_blocked', {
    failed: report.failed,
    count: report.total,
    defaultValue: "{failed} of {count} row can't be imported, so nothing will be written.",
    defaultValue_other: "{failed} of {count} rows can't be imported, so nothing will be written.",
  });
  const remedy = t('records.io.apply_blocked_fix', {
    count: report.failed,
    defaultValue:
      'Fix it and try again, or choose "Skip it and write the rest" under Import options.',
    defaultValue_other:
      'Fix them and try again, or choose "Skip it and write the rest" under Import options.',
  });
  return `${sentence} ${remedy}`;
}

/**
 * U16: "Download CSV"/"Download JSON" disclosed nothing about *how much* —
 * export honours the list's current filter and the trash toggle (verified:
 * `state:eq:CA` → 4 rows on screen, 4 rows in the file), and an admin
 * exporting for a backup right after filtering got a silent subset. Says
 * the scope in the menu item itself, so the count is read before the click
 * rather than discovered after opening the download.
 */
export function exportScopeLabel(
  t: Translate,
  { trashed, filtered, count }: { trashed: boolean; filtered: boolean; count: number },
): string {
  if (trashed) {
    return t('records.io.scope_trashed', {
      count,
      defaultValue: '{count} trashed record',
      defaultValue_other: '{count} trashed records',
    });
  }
  if (filtered) {
    return t('records.io.scope_filtered', {
      count,
      defaultValue: '{count} filtered record',
      defaultValue_other: '{count} filtered records',
    });
  }
  return t('records.io.scope_all', {
    count,
    defaultValue: 'all {count} records',
  });
}

/** The parser's own errors (`services/_io_upload.py`) are accurate but
 *  written for the log, not the person who just picked a file — one names a
 *  query parameter no browser upload can send, the other quotes a JSON
 *  parser's own message. Recognised by a stable substring rather than
 *  rewritten server-side, so this stays a UI concern (UX-5). */
export function friendlyImportError(t: Translate, raw: string): string {
  if (raw.includes('cannot tell whether this is JSON or CSV')) {
    return t('records.io.error_unknown_format', {
      defaultValue:
        "Couldn't tell whether that file is JSON or CSV — save it with a .json or .csv extension and try again.",
    });
  }
  if (raw.includes('is not valid JSON')) {
    return t('records.io.error_bad_json', {
      defaultValue:
        "That file isn't valid JSON — open it in a text editor and check it's complete.",
    });
  }
  return raw;
}
