import { useEffect, useRef } from 'react';

/** Async work may outlive its screen; only its network writes should continue. */
export function useMountedRef() {
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  return mounted;
}
