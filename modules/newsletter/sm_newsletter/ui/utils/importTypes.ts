/** Wire types of the import API (`web/schemas/imports.py`). */

export type ImportStatus = 'staged' | 'queued' | 'running' | 'done' | 'failed';
export type ImportKind = 'subscribed' | 'unsubscribed' | 'cleaned' | 'ignored';
export type RowErrorCode =
  | 'invalid_email'
  | 'cell_too_long'
  | 'tag_invalid'
  | 'invalid_value'
  | 'record_refused'
  | 'tags_unavailable';

/** Whether the list's `tags` field exists, can be created by the import, or cannot be. */
export type TagsTarget = 'present' | 'creatable' | 'missing';

/** `fields` maps a column index (as a string) to a target field key. */
export interface ImportMapping {
  fields: Record<string, string>;
  tags: boolean;
}

export interface ImportFile {
  name: string;
  kind: ImportKind;
  rows: number;
}

export interface ImportColumn {
  index: number;
  header: string;
}

export interface ImportField {
  key: string;
  label: string;
  type: string;
}

export interface ImportTargets {
  fields: ImportField[];
  tags: TagsTarget;
}

export interface ImportTag {
  label: string;
  value: string;
  count: number;
}

export interface ImportRowError {
  file: number | null;
  line: number | null;
  code: string;
  field: string | null;
}

export interface ImportJob {
  id: number;
  list_type_key: string;
  status: ImportStatus;
  files: ImportFile[];
  columns: ImportColumn[];
  mapping: Partial<ImportMapping>;
  targets: ImportTargets;
  tags_found: ImportTag[];
  total: number;
  duplicates: number;
  invalid: number;
  processed: number;
  created: number;
  updated: number;
  skipped: number;
  suppressed: number;
  failed: number;
  /** The first 50 only; `errors_total` counts them all and the CSV lists up to the stored cap. */
  errors: ImportRowError[];
  errors_total: number;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ImportSummary {
  id: number;
  list_type_key: string;
  status: ImportStatus;
  total: number;
  processed: number;
  created_at: string;
}
