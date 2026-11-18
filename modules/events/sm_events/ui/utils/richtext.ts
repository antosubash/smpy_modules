/** The description editor's own allow-list, the client half of
 *  `sm_events/content/richtext.py`. The server's sanitiser is the trust
 *  boundary; this one keeps the editor honest: HTML from the server, from a
 *  paste or from the field itself is rebuilt from allowed elements before it
 *  is shown or sent, so nothing else ever enters the page as markup. */

const KEEP = new Set([
  'p',
  'br',
  'strong',
  'em',
  'u',
  's',
  'a',
  'ul',
  'ol',
  'li',
  'blockquote',
  'h2',
  'h3',
]);
const RENAME: Record<string, string> = {
  b: 'strong',
  i: 'em',
  strike: 's',
  del: 's',
  div: 'p',
  h1: 'h2',
  h4: 'h3',
  h5: 'h3',
  h6: 'h3',
};
/** Elements whose contents are not text for a reader: dropped with everything in them. */
const DROP = new Set([
  'script',
  'style',
  'iframe',
  'object',
  'embed',
  'svg',
  'math',
  'template',
  'noscript',
  'textarea',
  'select',
  'option',
  'head',
  'title',
  'meta',
  'link',
  'base',
  'form',
  'button',
  'input',
  'audio',
  'video',
  'canvas',
  'img',
  'picture',
  'frame',
  'frameset',
]);
const MAX_DEPTH = 20;
/** Controls, spaces and zero-width or separator characters: a browser ignores
 *  them inside a URL scheme, so they are removed before the scheme is checked. */
const invisible = (ch: string): boolean => {
  const code = ch.charCodeAt(0);
  return (
    code <= 0x20 ||
    (code >= 0x7f && code <= 0x9f) ||
    (code >= 0x200b && code <= 0x200f) ||
    code === 0x2028 ||
    code === 0x2029 ||
    code === 0xfeff
  );
};
const SCHEME = /^(https?:|mailto:)/i;

/** The link address when it is one the server would keep (http, https, mailto). */
export function safeHref(raw: string | null | undefined): string | null {
  const href = Array.from(raw ?? '')
    .filter((ch) => !invisible(ch))
    .join('');
  return SCHEME.test(href) ? href : null;
}

function copy(from: Node, to: Node, depth: number): void {
  const doc = to.ownerDocument ?? document;
  for (const node of Array.from(from.childNodes)) {
    if (node.nodeType === 3) {
      to.appendChild(doc.createTextNode(node.nodeValue ?? ''));
      continue;
    }
    if (node.nodeType !== 1) continue;
    const element = node as Element;
    const raw = element.tagName.toLowerCase();
    if (DROP.has(raw)) continue;
    const tag = RENAME[raw] ?? raw;
    // Past the depth limit, or not allowed: keep the text, lose the element.
    if (!KEEP.has(tag) || depth >= MAX_DEPTH) {
      copy(element, to, depth);
      continue;
    }
    const clean = doc.createElement(tag);
    if (tag === 'a') {
      const href = safeHref(element.getAttribute('href'));
      if (href) clean.setAttribute('href', href);
    }
    copy(element, clean, depth + 1);
    to.appendChild(clean);
  }
}

/** The allowed elements of `html`, built fresh in a fragment that is not part of
 *  the page. The parsed input never runs: a `DOMParser` document has no
 *  scripts, no loading and no handlers. */
export function cleanFragment(html: string): DocumentFragment {
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  const out = document.createDocumentFragment();
  copy(parsed.body, out, 0);
  return out;
}

/** `html` as the allowed markup; the empty string when nothing but blanks is left. */
export function cleanHtml(html: string): string {
  const holder = document.createElement('div');
  holder.appendChild(cleanFragment(html));
  return holder.textContent?.trim() ? holder.innerHTML : '';
}

/** One spelling for the same content: `innerHTML` writes a non-breaking space as
 *  `&nbsp;` and leaves an apostrophe bare, while the server keeps the character
 *  and writes `&#x27;` inside an attribute. Comparing or emitting only this form
 *  means leaving a field without an edit never looks like a change. */
export function normalHtml(html: string): string {
  return cleanHtml(html)
    .replaceAll('&nbsp;', ' ')
    .replaceAll(/&#(?:x27|39);/gi, "'");
}
