/** Where focus goes when the Move dialog closes: the chip it came from. A write refetches and
 *  the grid rebuilds that chip, which drops the focus it had, so for a short while the
 *  return is retried against the rebuilt chip. It stops once the chip has focus, as soon as
 *  the user acts (a pointer press or a key), when a new return starts and on unmount. */
import { useCallback, useEffect, useRef } from 'react';
import type { Occurrence } from '../types';

const TICK_MS = 100;
const TICKS = 15;
/** Ticks to wait for the chip before the toolbar title takes the focus. */
const TITLE_AFTER = 5;

type FocusFn = (key: string) => boolean;

const title = () => document.querySelector<HTMLElement>('[data-testid="calendar-title"]')?.focus();
const lost = () => document.activeElement === document.body || document.activeElement === null;

export function useFocusReturn(focusRef: { current: FocusFn | null }) {
  const stop = useRef<(() => void) | null>(null);
  useEffect(() => () => stop.current?.(), []);

  return useCallback(
    (o: Occurrence, element: HTMLElement | null) => {
      stop.current?.();
      // At once, on the chip that is still there; the rebuild may replace it.
      if (element?.isConnected) element.focus();
      else if (!focusRef.current?.(o.key)) title();
      let ticks = 0;
      const end = () => {
        window.clearInterval(timer);
        document.removeEventListener('pointerdown', end, true);
        document.removeEventListener('keydown', end, true);
        stop.current = null;
      };
      const timer = window.setInterval(() => {
        ticks += 1;
        if (lost()) {
          if (focusRef.current?.(o.key)) return end();
          if (ticks >= TITLE_AFTER) {
            title();
            return end();
          }
        }
        if (ticks >= TICKS) end();
      }, TICK_MS);
      document.addEventListener('pointerdown', end, true);
      document.addEventListener('keydown', end, true);
      stop.current = end;
    },
    [focusRef],
  );
}
