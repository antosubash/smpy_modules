import { useCallback, useEffect, useRef } from 'react';
import type { ScopedRequest } from './useRequestScope';

/** Reads that replace each other (a list that refetches, an editor that
 *  reloads): `begin()` aborts the one before it, and `alive()` is false for
 *  any request a newer one superseded or that outlived the component. An
 *  aborted fetch is ignored by its caller, never shown as an error. */
export function useLatestRequest(): () => ScopedRequest {
  const state = useRef({ id: 0, controller: null as AbortController | null });
  useEffect(() => {
    const current = state.current;
    return () => {
      current.id += 1;
      current.controller?.abort();
    };
  }, []);
  return useCallback(() => {
    const current = state.current;
    current.controller?.abort();
    const controller = new AbortController();
    current.controller = controller;
    current.id += 1;
    const mine = current.id;
    return {
      signal: controller.signal,
      alive: () => current.id === mine && !controller.signal.aborted,
    };
  }, []);
}
