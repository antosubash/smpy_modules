import { useEffect, useRef } from 'react';

export function useSaveShortcut(save: () => Promise<void>, pending: boolean) {
  // ⌘S / Ctrl+S (R13, missing-UI M9). Read through refs so the listener is
  // installed once and still calls the current `save` — and so a second
  // press while one is in flight is ignored rather than queued behind it.
  const saveRef = useRef(save);
  saveRef.current = save;
  const pendingRef = useRef(pending);
  pendingRef.current = pending;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // U13: `event.key` is `'S'` with Shift held or CapsLock on — a plain
      // `!== 's'` missed ⇧⌘S and CapsLock+⌘S both, falling through to the
      // browser's own "Save page" dialog on the busiest data-entry screen in
      // the module. `event.code` would dodge the case question entirely, but
      // ties the shortcut to physical key position (wrong on a non-QWERTY
      // layout where the "S" character sits elsewhere) — comparing the
      // lowercased key is what every other single-letter shortcut here would
      // want too.
      if (event.key.toLowerCase() !== 's' || event.altKey) return;
      if (!(event.metaKey || event.ctrlKey)) return;
      // The browser's own "save this page" is never what someone means with
      // an editor open.
      event.preventDefault();
      if (pendingRef.current) return;
      void saveRef.current();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

}
