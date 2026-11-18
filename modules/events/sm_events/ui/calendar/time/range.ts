/** Fetch ranges: the visible range plus a margin, never longer than the API allows. */
import { Temporal } from 'temporal-polyfill';
import type { FilterQuery, OccurrenceQuery } from '../types';

export const RANGE_MARGIN_DAYS = 7;
export const MAX_RANGE_DAYS = 366;
export const DEFAULT_CREATE_MINUTES = 60;
/** The grid's slot (`slotDuration` in `adapter/options.ts`): a click selects one. */
export const SLOT_MINUTES = 30;

/** Aware ISO instants, half-open. */
export type Range = { start: string; end: string };

const DAY_MS = 86_400_000;
const ms = (iso: string): number => Temporal.Instant.from(iso).epochMilliseconds;
const iso = (millis: number): string => Temporal.Instant.fromEpochMilliseconds(millis).toString();

/** The visible range padded by `margin` days on each side. Past `MAX_RANGE_DAYS` the margin
 *  shrinks evenly (the visible range stays in the middle); a visible range that is itself
 *  too long is returned as it is, and the API answers `range_too_long`. */
export function paddedRange(visible: Range, margin: number = RANGE_MARGIN_DAYS): Range {
  const start = ms(visible.start);
  const end = ms(visible.end);
  const spare = MAX_RANGE_DAYS * DAY_MS - (end - start);
  if (spare <= 0) return { start: iso(start), end: iso(end) };
  const pad = Math.min(margin * DAY_MS, Math.floor(spare / 2));
  return { start: iso(start - pad), end: iso(end + pad) };
}

export function contains(outer: Range, inner: Range): boolean {
  return ms(outer.start) <= ms(inner.start) && ms(inner.end) <= ms(outer.end);
}

const sorted = (ids: readonly string[]): string[] => [...ids].sort();

/** Stable for the same filters in any order. */
export function filtersKey(q: FilterQuery): string {
  return JSON.stringify([sorted(q.calendars), sorted(q.categories), sorted(q.types), q.locale]);
}

export const rangeKey = (q: OccurrenceQuery): string => `${q.start}|${q.end}|${filtersKey(q)}`;
