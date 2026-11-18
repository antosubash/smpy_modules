import { router } from '@inertiajs/react';
import { useCallback, useEffect, useRef, useState } from 'react';

type Visit = { url: URL; method: string; data: unknown; replace: boolean };

/** Asking before the editor is left with edits the server does not hold. A tab
 *  close or reload asks through `beforeunload`; an Inertia visit (Back, a
 *  sub-event or parent link, the sidebar) is held and offered to the page as
 *  `pending`, which its own dialog answers with `leave` or `stay`. A partial
 *  reload (`only`) keeps the form mounted and is never held. `allow` lets the
 *  next visit through, for the one a successful create makes itself. */
export function useLeaveGuard(dirty: boolean) {
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const allowed = useRef(false);
  const held = useRef<Visit | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      if (allowed.current) return;
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);

  useEffect(
    () =>
      router.on('before', (event) => {
        const visit = event.detail.visit;
        if (!dirtyRef.current || allowed.current || visit.only.length > 0) return;
        event.preventDefault();
        held.current = {
          url: visit.url,
          method: visit.method,
          data: visit.data,
          replace: visit.replace,
        };
        setPending(true);
      }),
    [],
  );

  const leave = useCallback(() => {
    const visit = held.current;
    held.current = null;
    allowed.current = true;
    setPending(false);
    if (visit) {
      router.visit(visit.url, {
        method: visit.method as 'get',
        data: visit.data as Record<string, never>,
        replace: visit.replace,
      });
    }
  }, []);
  return {
    pending,
    stay: useCallback(() => {
      held.current = null;
      setPending(false);
    }, []),
    leave,
    allow: useCallback(() => {
      allowed.current = true;
    }, []),
  };
}
