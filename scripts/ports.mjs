// The one port guard. The Makefile (through the CLI at the bottom),
// playwright.config.ts and host/client_app/vite.config.ts all resolve the
// dev stack's ports here, so they cannot disagree about what a value means.
//
// A candidate counts only as a plain positive decimal (`^[1-9][0-9]*$`).
// Anything else (empty, `0`, `08`, `0x1f90`, `1e3`, a shell fragment) gets
// the default instead. The Makefile puts the result into an `lsof` argument
// and a `pkill` regex, so an unchecked value would abort the sweep or widen
// the match.
import { pathToFileURL } from 'node:url';

export const DEFAULT_API_PORT = '8000';
export const DEFAULT_UI_PORT = '5050';

const DEFAULTS = { api: DEFAULT_API_PORT, ui: DEFAULT_UI_PORT };

/**
 * The first non-empty candidate if it is a valid port, else `fallback`.
 * Works like Make's `$(or ...)`: a candidate that is set but invalid gives
 * the fallback. It does not fall through to the next candidate.
 *
 * @param {readonly (string | undefined)[]} candidates
 * @param {string} fallback
 * @returns {string}
 */
export function resolvePort(candidates, fallback) {
  const raw = candidates.find((c) => c !== undefined && c !== '');
  return raw !== undefined && /^[1-9][0-9]*$/.test(raw) ? raw : fallback;
}

// The Makefile's entry point: `node scripts/ports.mjs <api|ui> [candidate ...]`
// prints the resolved port.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [kind, ...candidates] = process.argv.slice(2);
  const fallback = DEFAULTS[kind];
  if (!fallback) {
    console.error('usage: node scripts/ports.mjs <api|ui> [candidate ...]');
    process.exit(2);
  }
  console.log(resolvePort(candidates, fallback));
}
