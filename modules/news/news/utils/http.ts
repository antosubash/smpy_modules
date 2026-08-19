/** Shared fetch plumbing for the news API clients.
 *
 * Split out of `api.ts` so the taxonomy client reuses one CSRF read and one
 * error decoder rather than growing a second copy that drifts from it.
 */

export const BASE = '/api/news';

const CSRF_COOKIE = 'news_csrf';

export function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

/** Turn a failed response into something worth showing a person.
 *
 * The body is only useful when it is our own JSON `detail`. An HTML error page
 * — which is what an auth or CSRF failure returns — would otherwise be thrown
 * verbatim and rendered as a wall of markup, leaking the whole Inertia payload
 * into the DOM.
 */
export async function errorFrom(response: Response): Promise<Error> {
  const text = await response.text();
  try {
    const detail = (JSON.parse(text) as { detail?: unknown }).detail;
    if (typeof detail === 'string') return new Error(detail);
    if (detail) return new Error(JSON.stringify(detail));
  } catch {
    // Not JSON — fall through to the status line rather than echo markup.
  }
  return new Error(`Request failed (${response.status} ${response.statusText})`.trim());
}

/** GET returning JSON, with the abort signal the callers all need. */
export async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
    signal,
  });
  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as T;
}

export async function write<T>(path: string, method: string, body?: unknown): Promise<T | null> {
  const token = readCookie(CSRF_COOKIE);
  const response = await fetch(`${BASE}${path}`, {
    method,
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(token ? { 'X-CSRF-Token': token } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await errorFrom(response);
  return response.status === 204 ? null : ((await response.json()) as T);
}
