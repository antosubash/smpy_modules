/** Mirrors `MAX_EVENT_DAYS` and `MAX_SERIES_EVENT_DAYS` in `sm_events/core/constants/__init__.py`
 *  (`limits.test.ts` reads them): the longest a one-off event, and one occurrence of a
 *  recurring one, may last. */
export const EVENT_MAX_DAYS = 366;
export const SERIES_EVENT_MAX_DAYS = 31;

/** `REGISTRATION_CAPACITY_MAX`: the most seats an event may offer (the error message names it). */
export const REGISTRATION_CAPACITY_MAX = 100_000;

/** `MAX_OCCURRENCES`: what the occurrences API returns before it says `truncated`. Only the
 *  notice's wording uses it. */
export const OCCURRENCE_LIMIT = 2000;

/** `SOURCE_CALL_MAX_ITEMS`: what one plugin source may contribute to a read before its status is
 *  `truncated`. Only the notice's wording uses it. */
export const SOURCE_ITEM_LIMIT = 500;
