/** The `media_api` view prop — `sm_records.media.MediaApi.props()`. */
export type MediaApi = {
  prefix: string;
  list_path: string;
  upload_path: string;
  /** `{id}` is replaced with the file's id. */
  file_url_template: string;
  meta_url_template: string;
  /** The list route's filename-search parameter, when it declares one.
   *  `file_storage` declares none, so the picker filters the loaded page. */
  search_param: string | null;
};

/** The slice of `file_storage`'s `StoredFileOut` the picker shows. */
export type MediaFile = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string | null;
};

export type MediaPage = { items: MediaFile[]; total: number; page: number; perPage: number };

/** Files per picker page — a multiple of 2, 3 and 4, so no grid row of the
 *  dialog is left half-filled at any breakpoint. */
export const MEDIA_PAGE_SIZE = 24;

const ID_PLACEHOLDER = '{id}';

export function fillId(template: string, id: string): string {
  return template.split(ID_PLACEHOLDER).join(encodeURIComponent(id));
}

export function fileUrl(api: MediaApi, id: string): string {
  return fillId(api.file_url_template, id);
}

/** A value saved before the picker existed: a full URL typed into the text
 *  box. Rendered as a link, never looked up as an id. */
export function isUrlValue(value: string): boolean {
  return /^https?:\/\//i.test(value.trim());
}

/** `file_storage`'s id (`models.py`'s `uuid.UUID` primary key), either in its
 *  canonical hyphenated form (what the picker stores — `str(uuid.UUID(...))`)
 *  or the bare 32 hex digits FastAPI's own `uuid.UUID` path converter also
 *  accepts. Nothing else counts, even a string that merely contains hex
 *  characters. */
const UUID_RE = /^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32})$/i;

export type MediaValueKind = 'id' | 'url' | 'path' | 'text';

/**
 * What a stored `media` value names — the single rule every renderer of one
 * (the list cell, the editor's chip, the pagebuilder widget) applies so only
 * a real file-library id is ever asked about:
 *
 * - `'id'` — a `file_storage` UUID (`UUID_RE`): look it up.
 * - `'url'` — a plain `http(s)://` address saved before the picker existed:
 *   a link, never looked up.
 * - `'path'` — a `/`-rooted value: already a usable address on this host, a
 *   link (a relative one), never looked up.
 * - `'text'` — anything else (an import row's `media/products/x.png`, or any
 *   other free-form legacy value): plain text, never looked up, never a red
 *   "File missing" for data that was simply never library-managed.
 */
export function mediaValueKind(value: string): MediaValueKind {
  const trimmed = value.trim();
  if (isUrlValue(trimmed)) return 'url';
  if (UUID_RE.test(trimmed)) return 'id';
  if (trimmed.startsWith('/')) return 'path';
  return 'text';
}

export function isImage(file: Pick<MediaFile, 'content_type'>): boolean {
  return file.content_type.toLowerCase().startsWith('image/');
}
