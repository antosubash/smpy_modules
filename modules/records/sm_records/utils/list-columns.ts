/**
 * Which columns the record list shows: the default rule (`listColumns`, the
 * first indexed fields, plus the first media field) and the column chooser's resolution of `?columns=`,
 * a saved choice or that default (`resolveListColumns`).
 *
 * Split out of `listing.ts` for the 300-line cap when the chooser landed on
 * top of cursor paging; `listing.ts` re-exports every name here, so every
 * `from '.../utils/listing'` import keeps working.
 *
 * See `docs/plans/2026-09-19-records-module-design.md` §7.2 — only indexed
 * fields are queryable, which is why sorting and the *default* columns only
 * ever look at `indexed: true` fields plus the server's fixed columns — and
 * the first `media` field, whose thumbnail is shown but never sorted. The
 * chooser may show any declared field, since every list row carries its full
 * `data`; only its header's sort differs.
 */

import type { SortState } from './listing';
import type { FieldDef, TypeRead } from './types';

export const MAX_LIST_COLUMNS = 4;

/**
 * The indexed-field columns rendered after `display_title` on the record
 * list. Capped at four so the table doesn't outgrow a normal viewport, and
 * taken in the type's own field order (not re-sorted) so the columns match
 * the order fields appear in on the schema editor.
 *
 * The type's `display_field` is skipped (UX-R5): the Title column already
 * prints exactly that field's value on every row, so a column for it spends
 * a quarter of the table's horizontal budget repeating the first column —
 * and, since the four-column cap bites before a type's later fields do, it
 * spends it instead of showing a field the user cannot otherwise see.
 */
export function listColumns(
  type: Pick<TypeRead, 'fields'> & Partial<Pick<TypeRead, 'display_field'>>,
): FieldDef[] {
  return type.fields
    .filter((field) => field.indexed && field.key !== type.display_field)
    .slice(0, MAX_LIST_COLUMNS);
}

// ---- Chosen columns ---------------------------------------------------

/** The most *field* columns the chooser lets a view carry. Envelope columns
 *  (below) are toggles on top: they are narrow, and a cap that counted them
 *  would already be spent by the default view. */
export const MAX_CHOSEN_COLUMNS = 8;

/** The record's own columns the chooser offers beside the declared fields.
 *  Title, the tick box and Actions are fixed and never offered. Every one of
 *  these keys is a reserved field key (`constants.RESERVED_FIELD_KEYS`), so
 *  one `?columns=` list can name both kinds without ambiguity. */
export const ENVELOPE_COLUMNS = [
  'status',
  'locale',
  'position',
  'published_at',
  'updated_at',
] as const;
export type EnvelopeColumnKey = (typeof ENVELOPE_COLUMNS)[number];

export type ListColumn =
  | { kind: 'envelope'; key: EnvelopeColumnKey }
  | { kind: 'field'; key: string; field: FieldDef };

/** Where a list's columns came from: the link, this browser's saved choice
 *  for the type, or the built-in rule. */
export type ColumnSource = 'url' | 'saved' | 'default';

export type ResolvedColumns = {
  columns: ListColumn[];
  source: ColumnSource;
  /** `?columns=` keys this type has no column for — dropped, and named in a
   *  notice rather than failing the page. */
  unknown: string[];
  /** Field keys past `MAX_CHOSEN_COLUMNS` in the link, dropped likewise. */
  truncated: number;
};

type ColumnType = Pick<TypeRead, 'fields'> & Partial<Pick<TypeRead, 'display_field'>>;

/** Everything the chooser can offer for a type, envelope first. Language is
 *  offered only where the list shows language UI at all. */
export function availableColumns(type: ColumnType, showLocale: boolean): ListColumn[] {
  const envelope = ENVELOPE_COLUMNS.filter((key) => key !== 'locale' || showLocale);
  return [
    ...envelope.map((key): ListColumn => ({ kind: 'envelope', key })),
    ...type.fields.map((field): ListColumn => ({ kind: 'field', key: field.key, field })),
  ];
}

/**
 * The type's first `media` field, or `null` when it has none. The default
 * view adds it after the indexed fields, so a list of products shows its
 * thumbnails without anyone opening the chooser; beyond that it is an
 * ordinary chooser column (unsortable, like every non-indexed field) that
 * can be hidden or moved. One, not all: a row of thumbnails per record is a
 * different screen.
 */
export function firstMediaField(type: Pick<TypeRead, 'fields'>): FieldDef | null {
  return type.fields.find((field) => field.type === 'media') ?? null;
}

/** The default view, as a key list: Status, Language, `listColumns`, the
 *  first media field, Position, Published on, Updated — "Reset to default"
 *  returns here. */
export function defaultColumnKeys(type: ColumnType, showLocale: boolean): string[] {
  const fields = listColumns(type).map((field) => field.key);
  const media = firstMediaField(type);
  if (media) fields.push(media.key);
  const locale = showLocale ? ['locale'] : [];
  return ['status', ...locale, ...fields, 'position', 'published_at', 'updated_at'];
}

function pickColumns(keys: readonly string[], byKey: Map<string, ListColumn>) {
  const columns: ListColumn[] = [];
  const unknown: string[] = [];
  const seen = new Set<string>();
  let fields = 0;
  let truncated = 0;
  for (const raw of keys) {
    const key = raw.trim();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    const column = byKey.get(key);
    if (!column) unknown.push(key);
    else if (column.kind === 'field' && fields >= MAX_CHOSEN_COLUMNS) truncated += 1;
    else {
      if (column.kind === 'field') fields += 1;
      columns.push(column);
    }
  }
  return { columns, unknown, truncated };
}

/**
 * The list's columns, in order. Precedence: a `?columns=` in the link, then
 * the choice this browser saved for the type, then `defaultColumnKeys`.
 * Both explicit sources are validated against the type: an unknown key is
 * dropped (the link's are reported back in `unknown`), duplicates collapse,
 * and field keys past the cap are cut. A link whose every key is unknown
 * falls through to the next source, so a stale shared link still shows a
 * useful list; an *empty* `?columns=` is a real choice (Title only).
 */
export function resolveListColumns({
  type,
  showLocale,
  raw,
  saved,
}: {
  type: ColumnType;
  showLocale: boolean;
  raw: string | null;
  saved: readonly string[] | null;
}): ResolvedColumns {
  const byKey = new Map(availableColumns(type, showLocale).map((c) => [c.key, c]));
  if (raw !== null) {
    const tokens = raw.split(',').filter((token) => token.trim());
    const picked = pickColumns(tokens, byKey);
    if (picked.columns.length > 0 || tokens.length === 0) return { ...picked, source: 'url' };
    const fallback = resolveListColumns({ type, showLocale, raw: null, saved });
    return { ...fallback, unknown: picked.unknown };
  }
  if (saved) {
    const picked = pickColumns(saved, byKey);
    if (picked.columns.length > 0 || saved.length === 0) {
      return { columns: picked.columns, source: 'saved', unknown: [], truncated: 0 };
    }
  }
  const columns = pickColumns(defaultColumnKeys(type, showLocale), byKey).columns;
  return { columns, source: 'default', unknown: [], truncated: 0 };
}

/** Whether a column change hides the column the list is sorted by — the
 *  sort is then dropped. A sort on anything that is not a choosable column
 *  (Title, `created_at` from a hand-written link) is never touched. */
export function sortHiddenBy(
  sort: SortState,
  next: readonly ListColumn[],
  available: readonly ListColumn[],
): boolean {
  if (!sort || !available.some((c) => c.key === sort.field)) return false;
  return !next.some((c) => c.key === sort.field);
}
