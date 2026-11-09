import { matchPath } from './trackingPaths';

export type Scalar = string | number | boolean;
export type TrackingProperty = {
  id: string;
  kind: 'public' | 'application';
  route_patterns: string[];
  utm_parameters: string[];
  event_allowlist: Record<string, string[]>;
};
export type AnalyticsConfig = { properties: TrackingProperty[] };
let active: AnalyticsConfig = { properties: [] };
let currentUrl = '';

export function privacyRequested(): boolean {
  return (
    typeof navigator === 'undefined' ||
    navigator.doNotTrack === '1' ||
    (navigator as Navigator & { globalPrivacyControl?: boolean }).globalPrivacyControl === true
  );
}

function eventId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

async function send(
  property: TrackingProperty,
  kind: 'pageview' | 'event',
  name?: string,
  values: Record<string, Scalar> = {},
): Promise<void> {
  if (privacyRequested() || !currentUrl) return;
  const url = new URL(currentUrl, window.location.origin);
  const path = matchPath(url.pathname, property.route_patterns, property.kind);
  if (path === null) return;
  if (kind === 'event' && (!name || !Object.hasOwn(property.event_allowlist, name))) return;
  const allowed = name ? property.event_allowlist[name] : [];
  const properties = Object.fromEntries(
    Object.entries(values).filter(
      ([key, value]) =>
        allowed.includes(key) && ['string', 'number', 'boolean'].includes(typeof value),
    ),
  );
  const utm = Object.fromEntries(
    property.utm_parameters.flatMap((key) => {
      const value = url.searchParams.get(key);
      return value === null ? [] : [[key, value.slice(0, 200)]];
    }),
  );
  let referrer = '';
  try {
    referrer = document.referrer ? new URL(document.referrer).hostname : '';
  } catch {
    /* An invalid referrer is omitted. */
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 3000);
  try {
    await fetch('/api/analytics/collect', {
      method: 'POST',
      credentials: 'same-origin',
      signal: controller.signal,
      keepalive: true,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        property_id: property.id,
        event_id: eventId(),
        kind,
        path,
        referrer,
        name,
        properties,
        utm,
      }),
    });
  } catch {
    /* Analytics must never interrupt navigation or retry personal data. */
  } finally {
    clearTimeout(timer);
  }
}

/** Replace configuration on every navigation, including tenant switches. */
export function initAnalytics(
  config: AnalyticsConfig,
  url = typeof window === 'undefined' ? '' : window.location.href,
): void {
  active = config;
  currentUrl = url;
  if (privacyRequested()) return;
  for (const property of active.properties) void send(property, 'pageview');
}

export async function track(name: string, properties: Record<string, Scalar> = {}): Promise<void> {
  await Promise.all(active.properties.map((property) => send(property, 'event', name, properties)));
}
