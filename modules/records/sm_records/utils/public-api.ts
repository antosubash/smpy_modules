/**
 * Anonymous `fetch` client for the records module's *public* read API
 * (design doc §10), as consumed by the `RecordsList` Puck widget
 * (`components/widget/`).
 *
 * Deliberately separate from `utils/api.ts`: that file talks to
 * `/api/records/*`, which requires a session, and every request it sends
 * carries `credentials: 'same-origin'` on the assumption there is a session
 * to send. This module talks to `{public_route_prefix}/*` — no session, no
 * cookie, callable from a visitor who has never logged in — so the two must
 * never merge into one client that quietly assumes auth either way.
 *
 * `public_route_prefix` is a DB-backed setting (design §11) with no shared
 * Inertia prop carrying it onto an arbitrary pagebuilder page (it currently
 * rides along only on the records module's own TypeEditor screen — see
 * `endpoints/views.py::_editor_context`), so the widget cannot read it from
 * a shared prop the way the design doc's "if the host exposes one" allows
 * for. `DEFAULT_PUBLIC_PREFIX` is therefore the widget's own field default,
 * and an operator who changed the setting away from it re-points the widget
 * by editing that one field.
 */

import type { FilterOp } from './types';
import { FILTER_OPS } from './types';

export type PublicRecordItem = {
  uuid: string;
  slug: string | null;
  display_title: string;
  published_at: string | null;
  data: Record<string, unknown>;
};

export type PublicRecordPage = {
  items: PublicRecordItem[];
  total: number;
  page: number;
  page_size: number;
  /** How to show a `media` value to a visitor: a URL with `{id}` in it, or
   *  `null` when the media library does not serve files anonymously — which
   *  the framework `file_storage` module does not (`format.ts::publicMediaSrc`). */
  media_url_template?: string | null;
};

export const DEFAULT_PUBLIC_PREFIX = '/api/records/public';

export const MIN_LIMIT = 1;
export const MAX_LIMIT = 50;
export const DEFAULT_LIMIT = 10;

/** Strip trailing slashes and fall back to the default when blank.
 *
 * Never rewrites a leading slash: a prefix an operator mistyped without one
 * is a config problem for `RecordsSettings.check_public_route_prefix` to
 * catch, not something this function should silently paper over.
 */
export function normalizePublicPrefix(prefix: string | null | undefined): string {
  const trimmed = (prefix ?? '').trim();
  const base = trimmed === '' ? DEFAULT_PUBLIC_PREFIX : trimmed;
  const stripped = base.replace(/\/+$/, '');
  return stripped === '' ? DEFAULT_PUBLIC_PREFIX : stripped;
}

/** Clamp to the block field's own declared range (1–50). A value outside it
 *  reaches here only if content was hand-edited outside the field's `min`/
 *  `max`, so this is a defensive floor/ceiling, not the primary guard. */
export function clampLimit(limit: unknown): number {
  const n = typeof limit === 'number' && Number.isFinite(limit) ? Math.trunc(limit) : Number.NaN;
  const base = Number.isNaN(n) ? DEFAULT_LIMIT : n;
  return Math.min(MAX_LIMIT, Math.max(MIN_LIMIT, base));
}

const FILTER_TERM = /^[a-z][a-z0-9_]*$/;

/** Light client-side check of one `field:op:value` term — enough to catch a
 *  typo before it reaches the network, not a re-implementation of the
 *  server's grammar (`sm_records._grammar._parse_filter`). Splits on the
 *  first two colons only, so a value that itself carries a colon (a
 *  timestamp, a URL) is not truncated. An empty string is valid: it means
 *  "no filter". */
export function isValidFilterTerm(raw: string): boolean {
  const trimmed = raw.trim();
  if (trimmed === '') return true;
  const parts = trimmed.split(':');
  if (parts.length < 3) return false;
  const [field, op, ...rest] = parts;
  if (!FILTER_TERM.test(field)) return false;
  if (!(FILTER_OPS as readonly string[]).includes(op)) return false;
  const value = rest.join(':');
  return value.length > 0 || (op as FilterOp) === 'is_null';
}

/** Light client-side check of one `sort` term (`field` or `-field`). Empty
 *  is valid: it means "server default order". */
export function isValidSortTerm(raw: string): boolean {
  const trimmed = raw.trim();
  if (trimmed === '') return true;
  const field = trimmed.startsWith('-') ? trimmed.slice(1) : trimmed;
  return FILTER_TERM.test(field);
}

export type BuildPublicListUrlOptions = {
  prefix?: string | null;
  typeKey: string;
  limit?: number;
  filter?: string;
  sort?: string;
  /** Blank (the default) omits the param entirely — the public API then
   *  answers with the default content locale, never "every locale" (design
   *  §4.4). */
  locale?: string;
};

/** `{prefix}/{typeKey}?page_size=&filter=&sort=` — the one anonymous list
 *  route the widget calls. `filter`/`sort` are single terms (§ the block's
 *  own prop help): the server's grammar happily repeats `?filter=`, but nothing
 *  here needs more than one term at a time, and a second delimiter layered on
 *  top of the term's own colons would just be one more thing to get wrong in
 *  a text field with no editor of its own. */
export function buildPublicListUrl(options: BuildPublicListUrlOptions): string {
  const prefix = normalizePublicPrefix(options.prefix);
  const typeKey = encodeURIComponent(options.typeKey.trim());
  const params = new URLSearchParams();
  params.set('page_size', String(clampLimit(options.limit)));
  const filter = (options.filter ?? '').trim();
  if (filter) params.set('filter', filter);
  const sort = (options.sort ?? '').trim();
  if (sort) params.set('sort', sort);
  const locale = (options.locale ?? '').trim();
  if (locale) params.set('locale', locale);
  return `${prefix}/${typeKey}?${params.toString()}`;
}

/** Fetch one page of a public type's published records. Throws on a non-2xx
 *  response or a network failure — the widget's render always wraps this in
 *  its own try/catch and shows a muted error line, never a thrown render. */
export async function fetchPublicRecords(
  options: BuildPublicListUrlOptions,
  signal?: AbortSignal,
): Promise<PublicRecordPage> {
  const url = buildPublicListUrl(options);
  const response = await fetch(url, {
    // 'omit', not 'same-origin': this client is the anonymous one the header
    // comment describes, and sending a session cookie to a surface that reads
    // no user contradicts it — the widget renders for a visitor who has none.
    credentials: 'omit',
    headers: { Accept: 'application/json' },
    signal,
  });
  if (!response.ok) {
    throw new Error(`records public API: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as PublicRecordPage;
}
