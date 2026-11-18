/** A small LRU of occurrence pages, each stored under the (padded) range it was fetched for. */

import { contains, filtersKey, type Range } from '../time/range';
import type { OccurrencePage } from '../types';

export { filtersKey };

export const CACHE_ENTRIES = 8;

type Entry = { range: Range; filters: string; page: OccurrencePage };

export class RangeCache {
  private entries = new Map<string, Entry>();

  constructor(private readonly limit: number = CACHE_ENTRIES) {}

  private id = (range: Range, filters: string) => `${range.start}|${range.end}|${filters}`;

  /** A page whose range contains `visible`, fetched with the same filters. Touches it. */
  find(visible: Range, filters: string): OccurrencePage | undefined {
    for (const [id, entry] of [...this.entries].reverse()) {
      if (entry.filters !== filters || !contains(entry.range, visible)) continue;
      this.entries.delete(id);
      this.entries.set(id, entry);
      return entry.page;
    }
    return undefined;
  }

  put(range: Range, filters: string, page: OccurrencePage): void {
    const id = this.id(range, filters);
    this.entries.delete(id);
    this.entries.set(id, { range, filters, page });
    while (this.entries.size > this.limit) {
      const oldest = this.entries.keys().next().value;
      if (oldest === undefined) break;
      this.entries.delete(oldest);
    }
  }

  clear(): void {
    this.entries.clear();
  }
}
