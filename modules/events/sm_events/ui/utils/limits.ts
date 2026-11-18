/** Mirrors `MAX_EVENT_DAYS` and `MAX_SERIES_EVENT_DAYS` in `sm_events/core/constants/__init__.py`
 *  (`limits.test.ts` reads them): the longest a one-off event, and one occurrence of a
 *  recurring one, may last. */
export const EVENT_MAX_DAYS = 366;
export const SERIES_EVENT_MAX_DAYS = 31;
