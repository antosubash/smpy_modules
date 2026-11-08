/** API helpers receive no page props, so remember the initial and later Inertia tokens.
 * Each distributable module owns its copy to avoid depending on an optional sibling.
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
