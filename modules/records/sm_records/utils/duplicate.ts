/**
 * "Save as copy" (Missing-item — the browser UX review's tenth finding
 * without a fix: no way to start a new record from an existing one). The
 * button lives on `RecordEditor`; this is the handoff between that page's
 * two visits, the one the person is leaving and the blank `/…/{key}/new`
 * they're about to land on.
 *
 * `sessionStorage`, the same mechanism `useRecordEditor`'s own `CREATED_FLAG`
 * uses: the action *navigates*, so nothing a hook holds survives the trip,
 * and a query parameter carrying a whole record's data would be both
 * unwieldy and a thing people copy and share, claiming to reopen a copy
 * that was already made. Scoped per type key, not per record — only one
 * duplicate can be in flight at a time, and a stale entry for a different
 * type must not leak into a "New" visit that has nothing to do with it.
 */

import type { FieldDef, RecordRead, RecordStatus } from './types';

export type DuplicatePayload = {
  data: Record<string, unknown>;
  status: RecordStatus;
  position: number;
};

function flagKey(typeKey: string): string {
  return `sm-records-duplicate:${typeKey}`;
}

/** Drop a field's value where the schema marks it `unique` (design §7.8) —
 *  the one part of "identical to the source" that cannot survive the copy:
 *  resubmitting it unchanged would guarantee the very next Save a 409, which
 *  is exactly the dead end this action exists to avoid walking anyone into.
 *  `undefined` rather than `null`: `JSON.stringify` below drops the key
 *  entirely, so the field opens on its own empty default, the same as any
 *  other blank field on a new record. */
function withoutUniqueValues(
  fields: FieldDef[],
  data: Record<string, unknown>,
): Record<string, unknown> {
  const uniqueKeys = new Set(fields.filter((field) => field.unique).map((field) => field.key));
  const copy: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(data)) {
    copy[key] = uniqueKeys.has(key) ? undefined : value;
  }
  return copy;
}

/** Remember `source` as the seed for the next `/…/{typeKey}/new` visit.
 *  uuid and slug never enter `DuplicatePayload` at all — the server assigns
 *  both fresh, so there is nothing here to strip them *from*. */
export function rememberDuplicate(typeKey: string, fields: FieldDef[], source: RecordRead): void {
  const payload: DuplicatePayload = {
    data: withoutUniqueValues(fields, source.data ?? {}),
    status: source.status,
    position: source.position,
  };
  try {
    window.sessionStorage.setItem(flagKey(typeKey), JSON.stringify(payload));
  } catch {
    // Private mode, blocked site data — the button still navigates; the
    // new-record form simply opens blank instead of prefilled.
  }
}

/** …and take it, once, for this type's new-record screen. Read-and-clear so
 *  a reload of `/…/new` (or a second, unrelated visit to it later) doesn't
 *  replay a stale copy. */
export function takeDuplicate(typeKey: string): DuplicatePayload | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(flagKey(typeKey));
    if (!raw) return null;
    window.sessionStorage.removeItem(flagKey(typeKey));
    const parsed = JSON.parse(raw) as unknown;
    if (
      !parsed ||
      typeof parsed !== 'object' ||
      typeof (parsed as DuplicatePayload).data !== 'object'
    ) {
      return null;
    }
    return parsed as DuplicatePayload;
  } catch {
    return null;
  }
}
