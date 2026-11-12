/** The CSRF header for this module's own requests (#342).
 *
 * The token is the framework's `csrfToken` shared prop, which every
 * signed-in page carries, read through `currentCsrfToken` from
 * `@simple-module-py/ui` (the rendered page, then every Inertia visit).
 * This module neither shares nor tracks a token of its own any more.
 *
 * What stays is what the framework's `apiFetch` does not cover. The
 * callers in `api.ts` and `io.ts` need the `Response` itself: its
 * `statusText`, an `AbortError` thrown for an aborted read (`apiFetch`
 * reports one as a network failure) and a 204 as nothing. So they stay on
 * a raw `fetch`, with this header added, and `isCsrfRefusal`
 * turns the framework's English 403 into this module's own message.
 */

import { currentCsrfToken } from '@simple-module-py/ui/lib/csrf-token';

export const CSRF_HEADER = 'X-CSRF-Token';

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/** The header a request of `method` needs: nothing for a read, and nothing on
 *  a page that carries no token (the server then refuses the write). */
export function csrfHeaders(method: string | undefined): Record<string, string> {
  if (!UNSAFE.has((method ?? 'GET').toUpperCase())) return {};
  const token = currentCsrfToken();
  return token ? { [CSRF_HEADER]: token } : {};
}

/** How the framework's `RequiresCsrf` 403 begins. Its English sentence is
 *  written for developers; a person is shown the module's own message. */
const REFUSAL_PREFIX = 'CSRF token missing or invalid';

export function isCsrfRefusal(status: number, detail: unknown): boolean {
  return status === 403 && typeof detail === 'string' && detail.startsWith(REFUSAL_PREFIX);
}
