import { useCallback, useSyncExternalStore } from 'react';

/** Tailwind's `sm` breakpoint, as a query — the width at which a table stops
 *  fitting and a card layout takes over. Shared by `RecordTable` and
 *  `Types` (U7) so the two card breakpoints cannot drift apart. */
const NARROW = '(max-width: 639.98px)';

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
