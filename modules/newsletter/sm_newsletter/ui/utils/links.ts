/**
 * What the editor's link control accepts, mirroring `content/urls.py`
 * `check_link` so a link the server would strip is refused where it is typed.
 */

const MAX_URL = 2000;
const BARE_DOMAIN = /^[^\s/:@\\]+\.[^\s/:@\\]{2,}(?:[/?#]\S*)?$/;
const BARE_EMAIL = /^[^\s/:@\\]+@[^\s/:@\\]+\.[^\s/:@\\]{2,}$/;

function plain(value: string): boolean {
  // biome-ignore lint/suspicious/noControlCharactersInRegex: control characters are the point
  return value.length <= MAX_URL && !/[\s\u0000-\u001f\u007f-\u009f​-‏‪-‮⁠-⁤﻿]/.test(value);
}

/** True for http(s) with a host, `mailto:` with an address, or a site path. */
export function isAllowedLink(value: string): boolean {
  if (!plain(value) || value.includes('{{') || value.includes('\\')) return false;
  if (/^https?:\/\//i.test(value)) {
    try {
      return new URL(value).hostname !== '';
    } catch {
      return false;
    }
  }
  if (/^mailto:/i.test(value)) return value.length > 'mailto:'.length;
  return value.startsWith('/') && !value.startsWith('//');
}

/** The address to link to for what was typed: `''` removes the link, `null`
 *  means the server would refuse it. A bare domain gets `https://`, a bare
 *  address `mailto:`. */
export function normalizeLink(input: string): string | null {
  const value = input.trim();
  if (value === '') return '';
  if (isAllowedLink(value)) return value;
  if (BARE_EMAIL.test(value) && isAllowedLink(`mailto:${value}`)) return `mailto:${value}`;
  if (BARE_DOMAIN.test(value) && isAllowedLink(`https://${value}`)) return `https://${value}`;
  return null;
}
