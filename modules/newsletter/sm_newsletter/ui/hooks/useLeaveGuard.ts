/**
 * Asking before the campaign editor is left with work the server does not hold.
 *
 * Closing or reloading the tab while anything is unsaved (`dirty`: inside the
 * debounce, after a failed save, or held back) asks through `beforeunload`, as
 * news, pagebuilder and records do. An in-app Inertia visit unmounts the editor,
 * which flushes what can be saved, so it asks only when something cannot be:
 * `held`, an unfinished block (records' `useUnsavedGuard`).
 */

import { router } from '@inertiajs/react';
import { useEffect, useRef } from 'react';

import { keys, translate } from '../utils/i18n';

export function useLeaveGuard({ dirty, held }: { dirty: boolean; held: boolean }) {
  const heldRef = useRef(held);
  heldRef.current = held;

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  useEffect(
    () =>
      router.on('before', (event) => {
        if (!heldRef.current || event.detail.visit.only.length > 0) return;
        if (!window.confirm(translate(keys.newsletter.editor.leave_held))) event.preventDefault();
      }),
    [],
  );
}
