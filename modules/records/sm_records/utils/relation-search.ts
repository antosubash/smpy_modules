/**
 * What the relation picker asks for when someone types — F9.
 *
 * Its own module rather than a closure inside `RelationPicker.tsx`: the
 * component is at the 300-line cap, and "which query finds a record by its
 * title, and what that costs" is a self-contained decision worth reading on
 * its own.
 */

import { buildFilterParam } from './api';
import { listRecords } from './api-records';
import type { RecordRead } from './types';

/** How many rows the dropdown shows. */
const RESULT_LIMIT = 10;

/** Below this many prefix hits the picker also asks for `contains`. Above it
 *  there is already more than a short list to choose from, and the second
 *  request would only add rows nobody scrolls to. */
const WIDEN_BELOW = 5;

/** Prefix first, substring only if the prefix found almost nothing (F9).
 *
 * `display_title:contains:<q>` is `ILIKE '%q%'` on `records_record`, which no
 * index can serve: it reads every row of the target type, on every keystroke
 * after the debounce, and grows linearly with the type.
 * `display_title:starts_with:<q>` is answered from
 * `ix_records_record_type_title_id`. A prefix is also what someone typing a
 * name means most of the time — so it is asked first and shown alone when it
 * is enough, and the expensive query is the fallback for "I remember a word
 * from the middle", not the default.
 *
 * `§7.2`'s rule still holds either way: a free-text search over the payload
 * does not exist, and asking for one returns a 400, not results.
 */
export async function searchByTitle(target: string, term: string): Promise<RecordRead[]> {
  const byPrefix = await listRecords(target, {
    page_size: RESULT_LIMIT,
    total: false,
    filter: buildFilterParam('display_title', 'starts_with', term),
  });
  if (byPrefix.items.length >= WIDEN_BELOW) return byPrefix.items;
  const bySubstring = await listRecords(target, {
    page_size: RESULT_LIMIT,
    total: false,
    filter: buildFilterParam('display_title', 'contains', term),
  });
  // Prefix matches first and never twice: `contains` is a superset of
  // `starts_with`, so the two pages overlap by construction.
  const seen = new Set(byPrefix.items.map((item) => item.uuid));
  return [...byPrefix.items, ...bySubstring.items.filter((item) => !seen.has(item.uuid))].slice(
    0,
    RESULT_LIMIT,
  );
}
