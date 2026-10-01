import { router } from '@inertiajs/react';
import { t } from '@simple-module-py/i18n';
import { useEffect, useRef } from 'react';

/**
 * Warn before leaving a page that holds unsaved edits (UX review R12c).
 *
 * Two exits are guarded: an Inertia visit (the sidebar, a "Cancel" link,
 * Back) via the router's global `before` event, and a full unload (tab
 * close, reload, external link) via `beforeunload`. Both editors call this
 * with their own dirty predicate; the hook is otherwise stateless so the
 * page keeps owning what "dirty" means.
 *
 * `allow` is a ref, not state: a save that then navigates away sets it
 * before calling `router.visit`, so the guard never asks about the edits
 * that were just written. Read `t` inside the handler, never at module
 * scope, so the confirm text follows the boot locale (CLAUDE.md § i18n).
 */
export function useUnsavedGuard(dirty: boolean): { allow: () => void } {
  const allowRef = useRef(false);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  useEffect(() => {
    const message = () =>
      t('records.common.unsaved_changes', {
        defaultValue: 'You have unsaved changes. Leave this page and lose them?',
      });
    const offBefore = router.on('before', (event) => {
      if (!dirtyRef.current || allowRef.current) return;
      // Partial reloads (`only:` visits, e.g. the list's own filtering) stay
      // on the page and keep the form mounted; only a real navigation asks.
      if (event.detail.visit.only.length > 0) return;
      if (!window.confirm(message())) event.preventDefault();
    });
    const onUnload = (event: BeforeUnloadEvent) => {
      if (!dirtyRef.current || allowRef.current) return;
      event.preventDefault();
      // Current Chrome/Firefox/Safari honour `preventDefault` alone; an
      // older engine only shows its dialog for a non-empty `returnValue`,
      // and the string itself has been ignored for years (polish note).
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onUnload);
    return () => {
      offBefore();
      window.removeEventListener('beforeunload', onUnload);
    };
  }, []);

  return {
    allow: () => {
      allowRef.current = true;
    },
  };
}
