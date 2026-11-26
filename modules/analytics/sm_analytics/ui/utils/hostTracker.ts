import { type AnalyticsConfig, initAnalytics, privacyRequested } from './tracker';

export type HostAnalyticsPage = {
  url: string;
  component?: string;
  status?: number;
  /** The host's resolved tenant, required for same-origin tenant switches. */
  tenantId?: string | null;
};
type Page = string | HostAnalyticsPage;
type Subscribe = (listener: (page: Page) => void) => () => void;
export type HostAnalyticsOptions = {
  shouldTrack?: (page: HostAnalyticsPage & { path: string }) => boolean;
};
const CONFIG_TTL = 180000;
const FAILURE_BACKOFF = 30000;

/** Start once per tab; reuse config only within the same origin and tenant. */
export function startHostAnalytics(
  subscribe: Subscribe,
  initialPage: Page = window.location.href,
  { shouldTrack }: HostAnalyticsOptions = {},
): () => void {
  let generation = 0;
  let previous = '';
  let previousHash = '';
  let previousKey = '';
  let previousEligible = false;
  let cached: {
    key: string;
    expires: number;
    config?: AnalyticsConfig;
    pending?: Promise<AnalyticsConfig | undefined>;
  };
  let pending: AbortController | undefined;
  const configuration = (key: string) => {
    if (cached?.key === key) {
      if (cached.pending) return cached.pending;
      if (Date.now() < cached.expires) return Promise.resolve(cached.config);
    }
    pending?.abort();
    const entry = { key, expires: 0 } as typeof cached;
    cached = entry;
    const controller = new AbortController();
    pending = controller;
    const timer = setTimeout(() => controller.abort(), 3000);
    entry.pending = fetch('/api/analytics/config', {
      credentials: 'same-origin',
      cache: 'no-store',
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error('Configuration unavailable');
        const config = (await response.json()) as AnalyticsConfig;
        if (!Array.isArray(config?.properties)) throw new Error('Invalid configuration');
        entry.config = config;
        entry.expires = Date.now() + CONFIG_TTL;
        return config;
      })
      .catch(() => {
        // Fail closed and bound retries even when no property is enabled.
        entry.expires = Date.now() + FAILURE_BACKOFF;
        return undefined;
      })
      .finally(() => {
        entry.pending = undefined;
        clearTimeout(timer);
      });
    return entry.pending;
  };
  const navigate = (value: Page) => {
    const page = typeof value === 'string' ? { url: value } : value;
    const absolute = new URL(page.url, window.location.origin);
    const key = JSON.stringify([absolute.origin, page.tenantId ?? null]);
    const hash = absolute.hash;
    absolute.hash = '';
    const eligible =
      absolute.origin === window.location.origin &&
      !privacyRequested() &&
      shouldTrack?.({ ...page, url: absolute.href, path: absolute.pathname }) !== false;
    const hashOnly =
      previousEligible &&
      eligible &&
      key === previousKey &&
      absolute.href === previous &&
      hash !== previousHash;
    previousKey = key;
    previousHash = hash;
    previousEligible = eligible;
    previous = absolute.href;
    if (hashOnly) return;
    const revision = ++generation;
    initAnalytics({ properties: [] });
    if (!eligible) return;
    void configuration(key).then((config) => {
      if (revision === generation && config) initAnalytics(config, absolute.href);
    });
  };
  const unsubscribe = subscribe(navigate);
  navigate(initialPage);
  return () => {
    ++generation;
    pending?.abort();
    unsubscribe();
    initAnalytics({ properties: [] });
  };
}
