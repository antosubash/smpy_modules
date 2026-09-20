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
};

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
  if (response.ok) return parsed as ImportReport;
  const report = (parsed as { report?: ImportReport } | null)?.report;
  if (report) return report;
  const detail = (parsed as { detail?: string } | null)?.detail;
  throw new Error(detail || `Import failed (${response.status})`);
}
