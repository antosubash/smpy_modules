import { useEffect, useState } from 'react';
import { api, BILLING_API } from '../utils/api';
import { isActivated } from '../utils/format';
import type { Status } from '../utils/types';

const INTERVAL_MS = 2000;
const MAX_TRIES = 15;

/**
 * After Stripe redirects back with ``?checkout=success`` the webhook may not
 * have landed yet — the redirect itself grants nothing. Poll the status until
 * a provider subscription shows up, then hand it over; give up after ~30s.
 */
export function useCheckoutPolling(
  active: boolean,
  csrf: string,
  onActivated: () => void,
): 'idle' | 'waiting' | 'timeout' {
  const [state, setState] = useState<'idle' | 'waiting' | 'timeout'>(active ? 'waiting' : 'idle');

  useEffect(() => {
    if (!active) return;
    let tries = 0;
    let cancelled = false;
    const timer = setInterval(async () => {
      tries += 1;
      try {
        const status = await api<Status>(`${BILLING_API}/status`, csrf);
        if (!cancelled && isActivated(status)) {
          clearInterval(timer);
          setState('idle');
          onActivated();
          return;
        }
      } catch {
        // Transient; keep polling until the budget runs out.
      }
      if (tries >= MAX_TRIES && !cancelled) {
        clearInterval(timer);
        setState('timeout');
      }
    }, INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [active, csrf, onActivated]);

  return state;
}
