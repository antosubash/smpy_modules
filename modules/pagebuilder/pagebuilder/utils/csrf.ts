/** The session's CSRF token, for the writes `request.ts` and `mediaApi.ts` send (#126).
 *
 * The API checks the framework's `RequiresCsrf`: every POST/PUT/PATCH/DELETE
 * needs the token in `X-CSRF-Token`. Every pagebuilder screen shares it as the
 * `csrf_token` Inertia prop (`pagebuilder/csrf.py`). The fetch and upload
 * helpers sit at module level and no page passes them a prop, so this keeps
 * the latest value: first the page the server rendered, then every page
 * Inertia navigates to.
 *
 * News and records ship the same file. All three read the framework's one
 * token under the framework's one prop name, so none imports another.
 */

import { router } from '@inertiajs/react';

export const CSRF_HEADER = 'X-CSRF-Token';
export const CSRF_PROP = 'csrf_token';

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

let current = '';

function remember(props: unknown): void {
  const token = (props as Record<string, unknown> | null | undefined)?.[CSRF_PROP];
  if (typeof token === 'string' && token) current = token;
}

/** The first page, from the JSON Inertia 3 renders it into. Read because this
 *  module can load after the first `navigate` event has already fired. */
function initialProps(): unknown {
  const script = document.querySelector('script[data-page="app"][type="application/json"]');
  try {
    return script?.textContent
      ? (JSON.parse(script.textContent) as { props?: unknown }).props
      : null;
  } catch {
    return null;
  }
}

if (typeof document !== 'undefined') {
  remember(initialProps());
  try {
    router.on('navigate', (event) => remember(event.detail?.page?.props));
  } catch {
    // A component test's partial mock of `@inertiajs/react` has no `router`.
  }
}

/** The header a request of `method` needs: nothing for a read, and nothing on
 *  a page that was never handed a token (the server then refuses the write). */
export function csrfHeaders(method: string | undefined): Record<string, string> {
  if (!UNSAFE.has((method ?? 'GET').toUpperCase()) || !current) return {};
  return { [CSRF_HEADER]: current };
}

/** How the framework's `RequiresCsrf` 403 begins. Its English sentence is
 *  written for developers; a person is shown the module's own message. */
const REFUSAL_PREFIX = 'CSRF token missing or invalid';

export function isCsrfRefusal(status: number, detail: unknown): boolean {
  return status === 403 && typeof detail === 'string' && detail.startsWith(REFUSAL_PREFIX);
}

/** The same test against a raw response body, for the upload XHR. */
export function isCsrfRefusalBody(status: number, body: string): boolean {
  if (status !== 403) return false;
  try {
    return isCsrfRefusal(status, (JSON.parse(body) as { detail?: unknown }).detail);
  } catch {
    return false;
  }
}
