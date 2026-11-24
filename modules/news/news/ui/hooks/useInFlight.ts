import { useMemo, useState } from 'react';

import { createInFlightGuard } from '../utils/inFlight';
import { useMountedRef } from './useMountedRef';

/** `busy` for the buttons, and a `run` that refuses a second call while one is
 *  in flight — see `createInFlightGuard` for why state alone is not enough. */
export function useInFlight(cooldownMs = 0) {
  const [busy, setBusy] = useState(false);
  const mounted = useMountedRef();
  const run = useMemo(
    () =>
      createInFlightGuard((next) => {
        if (mounted.current) setBusy(next);
      }, cooldownMs),
    [cooldownMs, mounted],
  );
  return { busy, run };
}
