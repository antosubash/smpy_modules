import { useCallback, useRef } from 'react';

/**
 * Focus for a dialog opened without a Radix trigger: Radix returns focus to
 * the trigger it knows, so a dialog opened from state would drop it on
 * ``body`` and a keyboard user starts again from the top of the page.
 *
 * ``remember()`` when opening (the focused element is the control that
 * opened it); pass ``onCloseAutoFocus`` to the dialog's content.
 */
export function useReturnFocus() {
  const opener = useRef<HTMLElement | null>(null);
  const remember = useCallback(() => {
    const active = document.activeElement;
    opener.current = active instanceof HTMLElement && active !== document.body ? active : null;
  }, []);
  const onCloseAutoFocus = useCallback((event: Event) => {
    const target = opener.current;
    opener.current = null;
    if (target?.isConnected) {
      event.preventDefault();
      target.focus();
    }
  }, []);
  return { remember, onCloseAutoFocus };
}
