import { useCallback, useEffect, useRef } from 'react';

/** One request's lifetime: `alive` turns false once its scope ended (the
 *  dialog closed or reopened, the component unmounted), and `signal` aborts. */
export type ScopedRequest = { alive: () => boolean; signal: AbortSignal };

/** A lifetime guard for async work started from a dialog. `begin()` opens one
 *  request; when `active` changes or the component unmounts, every request
 *  still in flight goes stale and is aborted. A stale completion must do
 *  nothing: no state update, no `onGone`, no toast. */
export function useRequestScope(active: boolean): () => ScopedRequest {
  const generation = useRef(0);
  const inFlight = useRef(new Set<AbortController>());
  // biome-ignore lint/correctness/useExhaustiveDependencies: `active` is the trigger, not a read
  useEffect(
    () => () => {
      generation.current += 1;
      for (const controller of inFlight.current) controller.abort();
      inFlight.current.clear();
    },
    [active],
  );
  return useCallback(() => {
    const mine = generation.current;
    const controller = new AbortController();
    inFlight.current.add(controller);
    return {
      signal: controller.signal,
      alive: () => generation.current === mine && !controller.signal.aborted,
    };
  }, []);
}

/** `onGone` as a function that runs at most once per open dialog, and never
 *  while it is closed or after unmount. A caller's callback is usually a new
 *  function each render, so it is read through a ref. */
export function useGoneOnce(open: boolean, onGone?: () => void): () => void {
  const callback = useRef(onGone);
  callback.current = onGone;
  const state = useRef({ open: false, fired: false });
  useEffect(() => {
    state.current = { open, fired: false };
    return () => {
      state.current.open = false;
    };
  }, [open]);
  return useCallback(() => {
    const now = state.current;
    if (!now.open || now.fired) return;
    now.fired = true;
    callback.current?.();
  }, []);
}
