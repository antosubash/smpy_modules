import { router } from '@inertiajs/react';
import { useCallback, useEffect, useRef, useState } from 'react';

type Visit = { url: URL; method: string; data: unknown; replace: boolean };
/** The browser's step through its history that was held: where it was going. */
type Step = { key: string };
type Held = { kind: 'visit'; visit: Visit } | { kind: 'history'; step: Step };

/** The slice of the Navigation API this needs (not in every `lib.dom` yet). */
type NavigateEvent = Event & {
  navigationType: string;
  destination: { key: string; sameDocument: boolean };
};
type NavigationLike = EventTarget & {
  traverseTo: (key: string) => { finished: Promise<unknown> };
};
const navigation = (): NavigationLike | undefined =>
  (window as unknown as { navigation?: NavigationLike }).navigation;

/** Asking before the editor is left with edits the server does not hold.
 *
 *  The framework's `useLeaveGuard` is not used: it asks with the blocking
 *  `window.confirm`, and this page wants a localized in-page dialog (and has to
 *  guard Back and Forward, which that one does not).
 *
 *  - A tab close, reload or a step to another document asks through `beforeunload`.
 *  - An Inertia visit (a sub-event or parent link, the sidebar) is held on
 *    `before` and offered to the page as `pending`, which its dialog answers
 *    with `leave` or `stay`. A partial reload (`only`) is never held.
 *  - Back and Forward within the app fire no `before`, and by the time a
 *    `popstate` arrives Inertia's own listener has already restored the other
 *    page: it is registered on `window` at boot, and the browser runs a
 *    window's listeners in the order they were added, capture or not. So the
 *    step is held earlier, on the Navigation API's `navigate` event, which
 *    comes before the history moves and can be cancelled: the URL, the history
 *    and the form stay as they are. Leave then takes the same step. The browser
 *    lets a page cancel a step it did not start only once per user interaction,
 *    and a browser without the API cannot cancel at all; such a step is not
 *    held, and goes where the user asked (never a page that cannot be left).
 *
 *  `allow` lets the next visit through, for the one a successful create makes itself. */
export function useLeaveGuard(dirty: boolean, fallback: string) {
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const allowed = useRef(false);
  const held = useRef<Held | null>(null);
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

  useEffect(() => {
    const nav = navigation();
    if (!nav) return;
    const onNavigate = (event: Event) => {
      const e = event as NavigateEvent;
      if (!dirtyRef.current || allowed.current) return;
      if (e.navigationType !== 'traverse' || !e.destination.sameDocument || !e.cancelable) return;
      e.preventDefault();
      held.current = { kind: 'history', step: { key: e.destination.key } };
      setPending(true);
    };
    nav.addEventListener('navigate', onNavigate);
    return () => nav.removeEventListener('navigate', onNavigate);
  }, []);

  useEffect(
    () =>
      router.on('before', (event) => {
        const visit = event.detail.visit;
        if (!dirtyRef.current || allowed.current || visit.only.length > 0) return;
        event.preventDefault();
        held.current = {
          kind: 'visit',
          visit: { url: visit.url, method: visit.method, data: visit.data, replace: visit.replace },
        };
        setPending(true);
      }),
    [],
  );

  const leave = useCallback(() => {
    const now = held.current;
    held.current = null;
    allowed.current = true;
    setPending(false);
    if (now?.kind === 'visit') {
      router.visit(now.visit.url, {
        method: now.visit.method as 'get',
        data: now.visit.data as Record<string, never>,
        replace: now.visit.replace,
      });
    } else if (now?.kind === 'history') {
      // A step that cannot be taken any more (its entry is gone) still leaves.
      const step = navigation()?.traverseTo(now.step.key);
      if (!step) router.visit(fallback);
      else step.finished.catch(() => router.visit(fallback));
    }
  }, [fallback]);
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
