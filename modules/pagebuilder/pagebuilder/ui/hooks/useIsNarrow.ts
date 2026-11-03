import { useSyncExternalStore } from 'react';

/**
 * The width below which the drag canvas is not offered.
 *
 * From the design: drag-and-drop layout needs width. 900px is wide enough that
 * no laptop trips it and narrow enough to catch phones and portrait tablets,
 * which is exactly the set of screens where dragging a block into place is a
 * fight rather than a gesture.
 */
export const NARROW_MAX_WIDTH = 899;

const QUERY = `(max-width: ${NARROW_MAX_WIDTH}px)`;

function mediaQuery(): MediaQueryList | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null;
  return window.matchMedia(QUERY);
}

function subscribe(onChange: () => void): () => void {
  const mql = mediaQuery();
  if (!mql) return () => {};
  mql.addEventListener('change', onChange);
  return () => mql.removeEventListener('change', onChange);
}

function getSnapshot(): boolean {
  return mediaQuery()?.matches ?? false;
}

/**
 * Server render assumes wide.
 *
 * The mismatch has to fall one way or the other, and a narrow client that
 * corrects itself on hydration is better than a wide one that flashes a full
 * drag canvas onto a phone before taking it away.
 */
function getServerSnapshot(): boolean {
  return false;
}

/** True while the viewport is too narrow to edit on. Re-renders on resize. */
export function useIsNarrow(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
