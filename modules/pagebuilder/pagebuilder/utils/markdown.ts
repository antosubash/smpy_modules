import { splitLinks } from './markdown-links';

/**
 * A `- ` bullet or `1. ` item; indenting one under another nests it (#66). A
 * nested list takes the kind of its first item, which `childrenOrdered`
 * records — set only when that list is numbered, so a bullet tree stays plain
 * `{text, children}`.
 */
export type MarkdownListItem = {
  text: string;
  children: MarkdownListItem[];
  childrenOrdered?: boolean;
};

/**
 * `start` is set only when a numbered list doesn't begin at 1. Two members
 * rather than `type: 'ul' | 'ol'`, so `type === 'ul' || type === 'ol'` narrows
 * a `MarkdownBlock` to a list.
 */
export type MarkdownList =
  | { type: 'ul'; items: MarkdownListItem[]; start?: undefined }
  | { type: 'ol'; items: MarkdownListItem[]; start?: number };

export type MarkdownBlock = { type: 'h1' | 'h2' | 'h3' | 'p'; text: string } | MarkdownList;

// Leading whitespace, then `- `, or a number and `. ` / `) `. A tab counts as
// four spaces. Nine digits caps the number, as CommonMark does.
const BULLET = /^([ \t]*)- (.*)$/;
const NUMBERED = /^([ \t]*)(\d{1,9})[.)] (.*)$/;

export type ParseMarkdownBlocksOptions = {
  /**
   * Keep single newlines inside a paragraph (joined with "\n" instead of a
   * space) so renderers can emit soft line breaks. Widget textareas want
   * this — several rendered with `whitespace-pre-line` before markdown
   * support, so a bare newline has always been a visible break there. The
   * default (space-join) is standard markdown and what the HTML converter
   * and the Markdown widget keep using.
   */
  softBreaks?: boolean;
};

export function parseMarkdownBlocks(
  content: string,
  opts?: ParseMarkdownBlocksOptions,
): MarkdownBlock[] {
  const joiner = opts?.softBreaks ? '\n' : ' ';
  const lines = content.split(/\r?\n/);
  const blocks: MarkdownBlock[] = [];
  let paragraph: string[] = [];
  let list: MarkdownList | null = null;
  // Open lists, outermost first, each with the indent its items sit at.
  let listStack: { indent: number; items: MarkdownListItem[] }[] = [];

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      blocks.push({ type: 'p', text: paragraph.join(joiner) });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list) blocks.push(list);
    list = null;
    listStack = [];
  };
  const pushListItem = (indent: number, text: string, number: number | null) => {
    const item: MarkdownListItem = { text, children: [] };
    const type = number === null ? 'ul' : 'ol';
    // Switching between `-` and `1.` at the outermost level ends the list:
    // one element can't hold both kinds, and nesting the newcomer would
    // invent a hierarchy the author never wrote.
    const outermost = listStack.length === 0 || indent <= listStack[0].indent;
    if (list && outermost && list.type !== type) flushList();
    if (!list) {
      const items = [item];
      list =
        number !== null && number !== 1 ? { type: 'ol', items, start: number } : { type, items };
      listStack = [{ indent, items }];
      return;
    }
    while (listStack.length > 1 && indent < listStack[listStack.length - 1].indent) {
      listStack.pop();
    }
    const top = listStack[listStack.length - 1];
    // An item left of the list's first one becomes the new outermost level,
    // so a later indented item nests under it ("  - a\n- b\n  - c").
    if (listStack.length === 1 && indent < top.indent) top.indent = indent;
    if (indent > top.indent) {
      // Deeper than its predecessor: a child of the item above it, and the
      // first child decides whether that nested list is numbered.
      const parent = top.items[top.items.length - 1];
      if (parent.children.length === 0 && type === 'ol') parent.childrenOrdered = true;
      parent.children.push(item);
      listStack.push({ indent, items: parent.children });
    } else {
      top.items.push(item);
    }
  };
  const indentOf = (whitespace: string) => whitespace.replaceAll('\t', '    ').length;

  for (const line of lines) {
    const bullet = BULLET.exec(line);
    // As in CommonMark, only `1.` may interrupt a paragraph: a wrapped line that
    // happens to start with a year ("…founded in\n2019. Since then…") is prose.
    const numbered = bullet ? null : NUMBERED.exec(line);
    const startsList = numbered && (paragraph.length === 0 || Number(numbered[2]) === 1);
    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }
    if (line.startsWith('### ')) {
      flushParagraph();
      flushList();
      blocks.push({ type: 'h3', text: line.slice(4) });
    } else if (line.startsWith('## ')) {
      flushParagraph();
      flushList();
      blocks.push({ type: 'h2', text: line.slice(3) });
    } else if (line.startsWith('# ')) {
      flushParagraph();
      flushList();
      blocks.push({ type: 'h1', text: line.slice(2) });
    } else if (bullet) {
      flushParagraph();
      pushListItem(indentOf(bullet[1]), bullet[2], null);
    } else if (numbered && startsList) {
      flushParagraph();
      pushListItem(indentOf(numbered[1]), numbered[3], Number(numbered[2]));
    } else {
      flushList();
      paragraph.push(line.trim());
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}

// Alternatives are ordered longest-marker-first so "***x***" is captured
// whole as bold italic. The single-asterisk closer carries a (?!\*) guard so
// a lone `*` never pairs with the first asterisk of a following `**` (e.g.
// "* and **" stays literal instead of becoming a spurious <em>).
const INLINE_PATTERN = /(\*\*\*[^*\n]+\*\*\*|\*\*[^*\n]+\*\*|\*[^*\n]+\*(?!\*)|`[^`\n]+`)/g;

export function escapeHtml(text: string): string {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

export type InlineToken = {
  type: 'text' | 'strong' | 'em' | 'strongem' | 'code';
  content: string;
};

/**
 * Tokenize inline markdown (`***bold italic***`, `**strong**`, `*em*`,
 * `` `code` ``) into a flat token list. Single source of truth for the
 * converter's HTML output and the Markdown widget's React output — keep both
 * on this function.
 *
 * Capture parity: with `String.split(capturingRegex)`, only ODD-indexed parts
 * are captured separators. Even-indexed parts are literal text and are never
 * treated as markup, even when they look like markers — never an empty
 * <em>/<strong>/<code>. The triple-asterisk alternative must come first so
 * "***bold***" captures whole as a strongem span instead of leaving leftover
 * `*` markers that could mispair with later lone asterisks. Note the pattern
 * genuinely captures single-asterisk spans containing spaces
 * ("* 3 and 4 *" → em), which is intentional for this lightweight tokenizer.
 */
export function parseInlineTokens(text: string): InlineToken[] {
  const parts = text.split(INLINE_PATTERN);
  const tokens: InlineToken[] = [];
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];
    if (!part) continue;
    if (i % 2 === 0) {
      tokens.push({ type: 'text', content: part });
      continue;
    }
    let type: InlineToken['type'];
    let content: string;
    if (part.startsWith('***')) {
      type = 'strongem';
      content = part.slice(3, -3);
    } else if (part.startsWith('**')) {
      type = 'strong';
      content = part.slice(2, -2);
    } else if (part.startsWith('`')) {
      type = 'code';
      content = part.slice(1, -1);
    } else {
      type = 'em';
      content = part.slice(1, -1);
    }
    // Defensive: the pattern requires non-empty content between markers,
    // but never emit an empty token — fall back to the literal text.
    tokens.push(content ? { type, content } : { type: 'text', content: part });
  }
  return tokens;
}

function emphasisToHtml(text: string): string {
  return parseInlineTokens(text)
    .map((token) => {
      const escaped = escapeHtml(token.content);
      if (token.type === 'text') return escaped;
      if (token.type === 'strongem') {
        return `<strong><em>${escaped}</em></strong>`;
      }
      return `<${token.type}>${escaped}</${token.type}>`;
    })
    .join('');
}

const imageToHtml = (alt: string, src: string) =>
  `<img src="${escapeHtml(src)}" alt="${escapeHtml(alt)}">`;
const anchorToHtml = (href: string, inner: string) => `<a href="${escapeHtml(href)}">${inner}</a>`;

/**
 * One line of inline markdown → HTML, with no block wrapper. Links and images
 * go through the same `splitLinks` the widgets render with, so the export
 * keeps what the page shows and an unsafe href stays literal text in both.
 *
 * Exported for the places that need the emphasis but must not gain a `<p>`:
 * an image's `<figcaption>` is phrasing content the block renders inline, so
 * `markdownToHtml` would wrap it in a paragraph the page never had.
 */
export function inlineMarkdownToHtml(text: string): string {
  return splitLinks(text)
    .map((segment) => {
      if (segment.type === 'image') return imageToHtml(segment.alt, segment.src);
      if (segment.type === 'linkedImage') {
        return anchorToHtml(segment.href, imageToHtml(segment.alt, segment.src));
      }
      if (segment.type === 'link') return anchorToHtml(segment.href, emphasisToHtml(segment.label));
      return emphasisToHtml(segment.text);
    })
    .join('');
}

/** An item's nested list, which takes the kind of its first child. */
export function childList(item: MarkdownListItem): MarkdownList {
  return { type: item.childrenOrdered ? 'ol' : 'ul', items: item.children };
}

function listToHtml(list: MarkdownList): string {
  const html = list.items
    .map((item) => {
      const nested = item.children.length > 0 ? listToHtml(childList(item)) : '';
      return `<li>${inlineMarkdownToHtml(item.text)}${nested}</li>`;
    })
    .join('');
  const start = list.start === undefined ? '' : ` start="${list.start}"`;
  return `<${list.type}${start}>${html}</${list.type}>`;
}

export function markdownToHtml(content: string): string {
  return parseMarkdownBlocks(content)
    .map((block) => {
      if (block.type === 'ul' || block.type === 'ol') return listToHtml(block);
      return `<${block.type}>${inlineMarkdownToHtml(block.text)}</${block.type}>`;
    })
    .join('\n');
}
