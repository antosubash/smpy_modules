/**
 * Value formatting for the `RecordsList` widget's public render.
 *
 * Deliberately its own module rather than a reuse of `components/RecordCell`:
 * that component renders an Inertia `<Link>` to `/admin/records/...` for a
 * relation and reads `useT()` for a handful of labels, both of which are
 * admin-editor concerns a public page has no business pulling in (an
 * anonymous visitor following an admin link would just hit the login wall).
 * The value *coercions* it applies are copied faithfully — same dash for
 * empty, same ✓/– for booleans, same UTC-anchored date, same locale-aware
 * datetime — from `components/RecordCell.tsx`, which is the admin list's
 * formatting and the thing the design doc's "same value formatting" means.
 *
 * `utils/values.ts`'s `choicesOf` *is* reused, by `RecordsListBlock.tsx`'s
 * `resolveData` when it bakes a field's choices into `FieldMetaEntry`: it is
 * a pure function with no React or admin-only dependency, so there is no
 * reason to fork it.
 */

import { mediaValueKind } from '../../utils/media-api';
import type { FieldMetaEntry } from './types';

const DASH = '—';

function isRelationRef(value: unknown): value is { type: string; uuid: string } {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    typeof (value as { type?: unknown }).type === 'string' &&
    typeof (value as { uuid?: unknown }).uuid === 'string'
  );
}

/** `type:uuid` — the stored reference, verbatim. The public API never
 *  expands a relation (design §10), so there is no `display_title` to show
 *  in its place; the block's own prop help says as much. */
function formatRelationRef(value: unknown): string {
  if (isRelationRef(value)) return `${value.type}:${value.uuid}`;
  return DASH;
}

function choiceLabel(meta: FieldMetaEntry, raw: unknown): string {
  const match = meta.choices.find((c) => c.value === raw);
  return match ? match.label : String(raw);
}

function formatDate(raw: string): string {
  // A bare calendar day has no timezone of its own (design §7.3) — anchor
  // at UTC midnight and format in UTC so the displayed day cannot shift a
  // day for a visitor west of UTC. Locale is the viewer's own (`undefined`).
  const parsed = new Date(`${raw}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return raw;
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeZone: 'UTC' }).format(
    parsed,
  );
}

function formatDatetime(raw: string): string {
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(
    parsed,
  );
}

/** One column's display value, formatted the way the admin list's
 *  `RecordCell` formats it — minus the two things a public page cannot do
 *  (link a relation, read `useT()`). `meta` is `undefined` for a value whose
 *  field definition wasn't baked in (an older saved block, or a schema
 *  change since); it still renders, just without type-specific formatting. */
export function formatPublicValue(meta: FieldMetaEntry | undefined, value: unknown): string {
  if (value === null || value === undefined) return DASH;
  const type = meta?.type ?? typeof value;

  switch (type) {
    case 'boolean':
      return value ? '✓' : '–';
    case 'number':
    case 'integer':
      // `number` arrives as a string (Decimal's JSON encoding, design §7.3);
      // `integer` as a JSON number. Either way the wire value is the display
      // value.
      return String(value);
    case 'date':
      return typeof value === 'string' ? formatDate(value) : String(value);
    case 'datetime':
      return typeof value === 'string' ? formatDatetime(value) : String(value);
    case 'select':
      return meta ? choiceLabel(meta, value) : String(value);
    case 'multiselect': {
      const values = Array.isArray(value) ? value : [value];
      if (values.length === 0) return DASH;
      return values.map((v) => (meta ? choiceLabel(meta, v) : String(v))).join(', ');
    }
    case 'relation': {
      const refs = Array.isArray(value) ? value : [value];
      if (refs.length === 0) return DASH;
      return refs.map(formatRelationRef).join(', ');
    }
    default: {
      const text = String(value);
      return text.length > 80 ? `${text.slice(0, 80)}…` : text;
    }
  }
}

/** Whether `href` is safe to render as a real `<a>` on the public page
 *  (M5): a relative path (`/...`, not scheme-relative `//...`), or an
 *  absolute `http:`/`https:` URL. Everything else — `javascript:`, `data:`,
 *  a bare scheme-relative `//host` (which inherits the page's own protocol),
 *  or anything with no leading slash and no `http(s)` scheme — is rejected.
 *  The *template* this builds from is free text a pagebuilder editor types
 *  into a Puck field (`RecordsListBlock.tsx`'s `linkTemplate`), not trusted
 *  record data, so this has to hold even though every stored `slug`/`uuid`
 *  is already safe on its own. */
function safeHref(href: string): boolean {
  // A leading slash followed by *either* slash: per WHATWG URL both `//`
  // and `/\` enter the "special authority" state, so
  // `new URL('/\evil.example', 'https://good.example/p')` resolves to
  // `https://evil.example/` exactly as the `//` form does. The old guard
  // tested only `startsWith('//')` and let the backslash through (R6).
  if (/^\/[/\\]/.test(href)) return false;
  if (href.startsWith('/')) return true;
  return /^https:\/\//i.test(href) || /^http:\/\//i.test(href);
}

/** Fill `{slug}`/`{uuid}` in a link template. Empty template (or a record
 *  missing the placeholder's value) means "no link", per the field's own
 *  prop help — and so does a template that resolves to an unsafe scheme
 *  (M5), which renders the title as plain text instead of an anchor. */
export function buildRecordHref(
  template: string,
  record: { slug: string | null; uuid: string },
): string | null {
  const trimmed = template.trim();
  if (trimmed === '') return null;
  if (trimmed.includes('{slug}') && !record.slug) return null;
  // `replaceAll`, not `replace`: a template may legitimately name a
  // placeholder twice (`/a/{slug}/{slug}.html`), and substituting only the
  // first left a literal `{slug}` in the rendered href (R6).
  const href = trimmed.replaceAll('{slug}', record.slug ?? '').replaceAll('{uuid}', record.uuid);
  return safeHref(href) ? href : null;
}

/** The `src` for a `media` value on the public page, or `null` for "render
 *  nothing".
 *
 *  Only a `file_storage`-id-shaped value (`mediaValueKind`) is ever built
 *  from `media_url_template`, which the anonymous read API sends only when
 *  the host's media library serves files to a visitor with no session
 *  (`sm_records.media.public_file_url_template`). The framework
 *  `file_storage` module does not — it exempts no route from authentication
 *  and its download also demands `file_storage.download` — so on a stock host
 *  the template is `null` and an id-shaped value renders nothing: an `<img>`
 *  of a URL that answers a visitor with a 401 is a broken-image icon, and
 *  printing the stored id is noise. A legacy `https://` value is not
 *  rendered either: it is whatever an editor pasted, and a public page is not
 *  the place to find out what that was. A `/`-rooted value is already a
 *  usable address on this host, so it is used as the `src` directly, with no
 *  template and no library needed. Anything else — free-form legacy or
 *  seeded data that was never an id, a URL or a path — renders nothing rather
 *  than guessing it is an id and asking a template to resolve it. */
export function publicMediaSrc(value: unknown, template: string | null | undefined): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const kind = mediaValueKind(trimmed);
  if (kind === 'path') return safeHref(trimmed) ? trimmed : null;
  if (kind !== 'id' || !template) return null;
  const src = template.split('{id}').join(encodeURIComponent(trimmed));
  return safeHref(src) ? src : null;
}
