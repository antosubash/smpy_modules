import { useEffect, useState } from 'react';

/** Async work may outlive its screen; only its network writes should continue. */
export function useMountedRef(identity?: number) {
  const [mounted, setMounted] = useState({ identity, current: true });
  if (mounted.identity !== identity) setMounted({ identity, current: true });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, [mounted]);
  return mounted;
}
