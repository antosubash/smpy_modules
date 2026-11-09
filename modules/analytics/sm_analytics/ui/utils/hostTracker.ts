import { type AnalyticsConfig, initAnalytics, privacyRequested } from './tracker';

type Subscribe = (listener: (url: string) => void) => () => void;
/** Host adapter: configuration is always re-resolved under the current tenant. */
export function startHostAnalytics(
  subscribe: Subscribe,
  initialUrl = window.location.href,
): () => void {
  let generation = 0;
  let previous = '';
  let previousHash = '';
  let pending: AbortController | undefined;
  const navigate = (url: string) => {
    const absolute = new URL(url, window.location.origin);
    const hash = absolute.hash;
    absolute.hash = '';
    const hashOnly = absolute.href === previous && hash !== previousHash;
    previousHash = hash;
    if (hashOnly) return;
    previous = absolute.href;
    const revision = ++generation;
    pending?.abort();
    initAnalytics({ properties: [] });
    if (privacyRequested()) return;
    const controller = new AbortController();
    pending = controller;
    const timer = setTimeout(() => controller.abort(), 3000);
    void fetch('/api/analytics/config', {
      credentials: 'same-origin',
      cache: 'no-store',
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) return;
        const config = (await response.json()) as AnalyticsConfig;
        if (revision === generation && Array.isArray(config.properties))
          initAnalytics(config, absolute.href);
      })
      .catch(() => {
        /* Configuration failures leave tracking disabled. */
      })
      .finally(() => clearTimeout(timer));
  };
  const unsubscribe = subscribe(navigate);
  navigate(initialUrl);
  return () => {
    ++generation;
    pending?.abort();
    unsubscribe();
    initAnalytics({ properties: [] });
  };
}
