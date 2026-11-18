import { router } from '@inertiajs/react';
import { useCallback, useEffect, useRef, useState } from 'react';

/** How long a history step may take to show up as a `popstate` before there is none. */
const STEP_WAIT_MS = 250;

type Visit = { url: URL; method: string; data: unknown; replace: boolean };
/** What is being held: an Inertia visit, or a step through the browser history. */
type Pending = 'visit' | 'history' | null;

/** Asking before the editor is left with edits the server does not hold.
 *
 *  The framework's `useLeaveGuard` is not used: it asks with the blocking
 *  `window.confirm`, and this page wants a localized in-page dialog (and has to
 *  guard Back and Forward, which that one does not).
 *
 *  - A tab close or reload asks through `beforeunload`.
 *  - An Inertia visit (a sub-event or parent link, the sidebar) is held on
 *    `before` and offered to the page as `pending`, which its dialog answers
 *    with `leave` or `stay`. A partial reload (`only`) is never held.
 *  - Inertia fires no `before` for the browser's Back and Forward, so while the
 *    form is dirty one sentinel entry (the same page again) sits on top of the
 *    history. Back lands on the real entry; a capture-phase `popstate` listener
 *    swallows it before Inertia's own, pushes the sentinel back and asks. Leaving
 *    then steps back past both entries; staying changes nothing. When the editor
 *    was the first page of the tab there is nothing to step back to and no
 *    `popstate` follows, so Leave visits `fallback` instead: it always leaves. Once the form is
 *    clean again the sentinel is removed, so a saved page leaves no stray entry.
 *
 *  `allow` lets the next visit through, for the one a successful create makes
 *  itself; it answers whether that visit should replace the sentinel. */
export function useLeaveGuard(dirty: boolean, fallback: string) {
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const allowed = useRef(false);
  const held = useRef<Visit | null>(null);
  const sentinel = useRef(false);
  const dropping = useRef(false);
  const gone = useRef(false);
  const stepped = useRef(false);
  const [pending, setPending] = useState<Pending>(null);

  useEffect(
    () => () => {
      gone.current = true;
    },
    [],
  );

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

  useEffect(() => {
    if (!dirty) return;
    window.history.pushState(window.history.state, '', window.location.href);
    sentinel.current = true;
    return () => {
      if (!sentinel.current || allowed.current || gone.current) return;
      sentinel.current = false;
      dropping.current = true;
      window.history.back();
    };
  }, [dirty]);

  useEffect(() => {
    const onPop = (e: PopStateEvent) => {
      if (allowed.current) {
        stepped.current = true; // the step Leave asked for happened
        return;
      }
      if (dropping.current) {
        dropping.current = false;
        e.stopImmediatePropagation();
        return;
      }
      if (!dirtyRef.current || !sentinel.current) return;
      e.stopImmediatePropagation();
      window.history.pushState(window.history.state, '', window.location.href);
      held.current = null;
      setPending('history');
    };
    window.addEventListener('popstate', onPop, { capture: true });
    return () => window.removeEventListener('popstate', onPop, { capture: true });
  }, []);

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
        setPending('visit');
      }),
    [],
  );

  const leave = useCallback(() => {
    const visit = held.current;
    held.current = null;
    allowed.current = true;
    setPending(null);
    if (visit) {
      // The sentinel is the entry the visit replaces, so the stack looks as if
      // the guard had never been there.
      router.visit(visit.url, {
        method: visit.method as 'get',
        data: visit.data as Record<string, never>,
        replace: visit.replace || sentinel.current,
      });
    } else {
      stepped.current = false;
      if (sentinel.current) window.history.go(-2);
      else window.history.back();
      setTimeout(() => {
        if (!stepped.current && !gone.current) router.visit(fallback);
      }, STEP_WAIT_MS);
    }
  }, [fallback]);
  return {
    pending: pending !== null,
    stay: useCallback(() => {
      held.current = null;
      setPending(null);
    }, []),
    leave,
    allow: useCallback(() => {
      allowed.current = true;
      return sentinel.current;
    }, []),
  };
}
