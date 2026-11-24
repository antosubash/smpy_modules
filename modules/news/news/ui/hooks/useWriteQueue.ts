import { useCallback, useRef } from 'react';

/** Serialize writes, reading their version inside the callback at send time.
 * Both editor screens use this queue; a failed request must settle before the
 * next callback can decide whether it is still safe to send. */
export function useWriteQueue() {
  const tail = useRef<Promise<unknown>>(Promise.resolve());
  return useCallback(<T>(work: () => Promise<T>): Promise<T> => {
    const next = tail.current.then(work);
    tail.current = next.catch(() => undefined);
    return next;
  }, []);
}
