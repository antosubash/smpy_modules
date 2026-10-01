/**
 * Pure helpers behind `useRecordForm`'s raw-JSON round trip and dirty-check:
 * split out so the hook (state, effects, the callbacks the page actually
 * calls) stays under the 300-line cap without folding these into it, where
 * they'd read as more hook than they are — none of them touch React.
 */

import type { TypeRead } from './types';
import { buildPayload, toFormValues } from './values';

export function asObject(text: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(text);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function pretty(data: Record<string, unknown> | null): string {
  return JSON.stringify(data ?? {}, null, 2);
}

/** A payload as one comparable string, key order made irrelevant.
 *
 * `JSON.stringify` alone would call a re-ordered but identical payload a
 * change, and "is this form dirty" (R12c) has to answer about the *values* —
 * `buildPayload` walks the fields in declaration order, but a raw-JSON edit
 * round-trips through whatever order the person typed. */
export function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
      a < b ? -1 : a > b ? 1 : 0,
    );
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stable(item)}`).join(',')}}`;
  }
  return JSON.stringify(value) ?? 'null';
}

/** What the record looked like when it was loaded, in `stable()` form — the
 *  baseline `dirty` compares against. Derived through `toFormValues` and back
 *  so it is the same round trip the live values take: a stored value the form
 *  normalises (a datetime, an empty optional) must not read as an edit. */
export function baselineOf(
  fields: TypeRead['fields'],
  data: Record<string, unknown> | null,
): string {
  return stable(buildPayload(fields, toFormValues(fields, data), data));
}
