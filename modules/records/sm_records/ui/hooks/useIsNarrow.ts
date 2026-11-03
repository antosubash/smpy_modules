import { useCallback, useSyncExternalStore } from 'react';

/** Tailwind's `md` breakpoint, as a query — the width below which a table
 *  stops fitting and a card layout takes over. Shared by `RecordTable` and
 *  `Types` (U7) so the two card breakpoints cannot drift apart.
 *
 * U8: this was `sm` (639.98px) until the gap between 640px and ~1000px
 * turned out to be exactly where a table silently drops columns instead of
 * reflowing — at 720×450 (the WCAG 1.4.4/1.4.10 200%-zoom test point) the
 * record list kept only Title/Status/Customer/Products, with Total, the
 * dates and the Actions column (Delete) pushed off the right edge and no
 * scrollbar, shadow or fade to say so. Raising the breakpoint to `md`
 * (767.98px) means the card layout — which already carries every column's
 * data and the row action, just stacked — takes over before that gap
 * starts rather than after it ends. */
const NARROW = '(max-width: 767.98px)';

function matchesNarrow(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia(NARROW).matches;
}

/** Subscribed to rather than read once, so a rotation or a resized window
 *  swaps layouts without a reload. */
export function useIsNarrow(): boolean {
  const subscribe = useCallback((onChange: () => void) => {
    if (typeof window === 'undefined' || !window.matchMedia) return () => {};
    const query = window.matchMedia(NARROW);
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);
  // The server snapshot is the wide layout: nothing renders this on a
  // server today, and a table/list is the safer thing to hydrate into.
  return useSyncExternalStore(subscribe, matchesNarrow, () => false);
}
