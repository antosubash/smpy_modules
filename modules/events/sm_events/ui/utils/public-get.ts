/** The one anonymous `GET` of the public surface (the grid's occurrences, the blocks' routes).
 *  Plain `fetch`: there is no session to send a CSRF token for, and the endpoints only read.
 *  A refusal is an `ApiError` with the module's code; a body that is not JSON keeps the status as
 *  its code. */

import { ApiError } from './api';

export async function publicGet<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
    signal,
  });
  if (!response.ok) {
    let code = String(response.status);
    try {
      const body = (await response.json()) as { code?: string };
      if (typeof body.code === 'string') code = body.code;
    } catch {
      /* a body that is not JSON keeps the status as its code */
    }
    throw new ApiError(response.status, code);
  }
  return response.json() as Promise<T>;
}
