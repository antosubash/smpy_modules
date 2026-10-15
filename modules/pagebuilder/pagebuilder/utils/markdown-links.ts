// Links and images in inline markdown, with no React: the widgets render the
// segments as elements and the HTML export as markup, so both read the same
// `[label](href)` the same way and apply the same safety rules.

// A link href or image src: ONE level of balanced parentheses, so Wikipedia's
// `..._(disambiguation)` survives. A naive `[^)]+` stops at the first `)`,
// truncating the URL and leaking the remainder onto the page as stray text.
const HREF_SOURCE = String.raw`(?:[^\s()]|\([^\s()]*\))+`;
/** `![alt](src)` — the alt may be empty, as a decorative logo's is. */
const IMAGE_SOURCE = String.raw`!\[[^\]]*\]\(${HREF_SOURCE}\)`;

// Split first, so a link's label can still carry the emphasis markers the
// inline tokenizer understands ("[**Datenschutz**](/x)"). Anything the pattern
// can't parse falls through unchanged as literal text, so malformed input is
// always visible rather than dropped.
//
// Images (#66) split out the same way, a linked image `[![alt](src)](href)`
// first: tried as a plain link, its label would end at the image's own `]`.
const LINK_PATTERN = new RegExp(
  String.raw`(\[${IMAGE_SOURCE}\]\(${HREF_SOURCE}\)|${IMAGE_SOURCE}|\[[^\]]+\]\(${HREF_SOURCE}\))`,
  'g',
);
const IMAGE = new RegExp(String.raw`^!\[([^\]]*)\]\((${HREF_SOURCE})\)$`);
const LINKED_IMAGE = new RegExp(String.raw`^\[(${IMAGE_SOURCE})\]\((${HREF_SOURCE})\)$`);
const LINK = new RegExp(String.raw`^\[([^\]]+)\]\((${HREF_SOURCE})\)$`);

// Browsers strip leading C0 controls and spaces from a URL, so
// "\x01javascript:…" has no scheme to the check below but runs as one once
// it is an href. A URL with a control character in it is never legitimate.
// biome-ignore lint/suspicious/noControlCharactersInRegex: matching them is the point
const CONTROL_CHAR = /[\u0000-\u001f\u007f]/;

/**
 * Editor copy is not fully trusted (ContentEditors can write these fields),
 * so only well-known schemes and scheme-less (relative / anchor) hrefs become
 * anchors — `javascript:` & co. fall through and render as literal text,
 * visible rather than executable.
 */
export function isSafeHref(href: string): boolean {
  return hasAllowedScheme(href, ['http', 'https', 'mailto', 'tel']);
}

/**
 * Only http(s) and scheme-less sources (`/media/...`, `logo.png`) load.
 * `data:`, `javascript:` and the rest fall through to literal text, the same
 * way an unsafe link href does.
 */
export function isSafeImageSrc(src: string): boolean {
  return hasAllowedScheme(src, ['http', 'https']);
}

/** Scheme-less, or one of `schemes`; never a URL with a control character. */
function hasAllowedScheme(url: string, schemes: string[]): boolean {
  if (CONTROL_CHAR.test(url)) return false;
  const scheme = /^([a-zA-Z][a-zA-Z0-9+.-]*):/.exec(url);
  return !scheme || schemes.includes(scheme[1].toLowerCase());
}

export type LinkSegment =
  | { type: 'text'; text: string }
  | { type: 'image'; alt: string; src: string }
  | { type: 'link'; label: string; href: string }
  | { type: 'linkedImage'; alt: string; src: string; href: string };

/** `![alt](src)` as an image segment, or `null` if it isn't one or its src is unsafe. */
function image(markdown: string): { alt: string; src: string } | null {
  const match = IMAGE.exec(markdown);
  return match && isSafeImageSrc(match[2]) ? { alt: match[1], src: match[2] } : null;
}

/**
 * Inline markdown → text, image, link and linked-image segments, in order.
 * A link or image whose href/src is unsafe stays a text segment holding the
 * literal markup. Text segments still carry emphasis markers for
 * `parseInlineTokens`; a link's label does too.
 */
export function splitLinks(text: string): LinkSegment[] {
  const segments: LinkSegment[] = [];
  for (const part of text.split(LINK_PATTERN)) {
    if (!part) continue;
    const img = image(part);
    if (img) {
      segments.push({ type: 'image', ...img });
      continue;
    }
    const linked = LINKED_IMAGE.exec(part);
    const linkedImg = linked && image(linked[1]);
    if (linked && linkedImg && isSafeHref(linked[2])) {
      segments.push({ type: 'linkedImage', ...linkedImg, href: linked[2] });
      continue;
    }
    const link = LINK.exec(part);
    if (link && isSafeHref(link[2])) {
      segments.push({ type: 'link', label: link[1], href: link[2] });
      continue;
    }
    segments.push({ type: 'text', text: part });
  }
  return segments;
}
