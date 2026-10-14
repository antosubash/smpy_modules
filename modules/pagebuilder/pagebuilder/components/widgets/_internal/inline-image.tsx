import type { ReactNode } from 'react';

// A link href or image src: ONE level of balanced parentheses, so Wikipedia's
// `..._(disambiguation)` survives (see LINK_PATTERN in rich-text).
export const HREF_SOURCE = String.raw`(?:[^\s()]|\([^\s()]*\))+`;
/** `![alt](src)` — the alt may be empty, as a decorative logo's is. */
export const IMAGE_SOURCE = String.raw`!\[[^\]]*\]\(${HREF_SOURCE}\)`;
const IMAGE_EXACT = new RegExp(String.raw`^!\[([^\]]*)\]\((${HREF_SOURCE})\)$`);

/**
 * Only http(s) and scheme-less sources (`/media/...`, `logo.png`) load. Editor
 * copy is not fully trusted, so `data:`, `javascript:` and the rest fall
 * through to literal text, the same way an unsafe link href does.
 */
function isSafeImageSrc(src: string): boolean {
  const scheme = /^([a-zA-Z][a-zA-Z0-9+.-]*):/.exec(src);
  return !scheme || ['http', 'https'].includes(scheme[1].toLowerCase());
}

/**
 * `![alt](src)` → `<img>`, or `null` when the text is not exactly one image or
 * its src is unsafe (#66). Inline, so a line of logos sits in a row and a
 * paragraph of its own stacks; `max-w-full` keeps a large one inside the column.
 */
export function renderInlineImage(markdown: string, key: string): ReactNode | null {
  const match = IMAGE_EXACT.exec(markdown);
  if (!match || !isSafeImageSrc(match[2])) return null;
  return (
    <img
      key={key}
      src={match[2]}
      alt={match[1]}
      loading="lazy"
      className="inline-block h-auto max-w-full align-middle"
    />
  );
}
