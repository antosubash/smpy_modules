export type MarkdownBlock =
  | { type: 'h1' | 'h2' | 'h3' | 'p'; text: string }
  | { type: 'ul'; items: string[] };

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
  let listItems: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length > 0) {
      blocks.push({ type: 'p', text: paragraph.join(joiner) });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (listItems.length > 0) {
      blocks.push({ type: 'ul', items: listItems });
      listItems = [];
    }
  };

  for (const line of lines) {
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
    } else if (line.startsWith('- ')) {
      flushParagraph();
      listItems.push(line.slice(2));
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

/**
 * One line of inline markdown → HTML, with no block wrapper.
 *
 * Exported for the places that need the emphasis but must not gain a `<p>`:
 * an image's `<figcaption>` is phrasing content the block renders inline, so
 * `markdownToHtml` would wrap it in a paragraph the page never had.
 */
export function inlineMarkdownToHtml(text: string): string {
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

export function markdownToHtml(content: string): string {
  return parseMarkdownBlocks(content)
    .map((block) => {
      if (block.type === 'ul') {
        const items = block.items.map((item) => `<li>${inlineMarkdownToHtml(item)}</li>`).join('');
        return `<ul>${items}</ul>`;
      }
      return `<${block.type}>${inlineMarkdownToHtml(block.text)}</${block.type}>`;
    })
    .join('\n');
}
