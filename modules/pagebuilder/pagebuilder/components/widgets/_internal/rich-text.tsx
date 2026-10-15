import { type CSSProperties, Fragment, type ReactNode } from 'react';
import {
  type MarkdownBlock,
  parseInlineTokens,
  parseMarkdownBlocks,
} from '../../../utils/markdown';
import { splitLinks } from '../../../utils/markdown-links';
import { cn } from '../../../utils/widgetUtils';
import { renderInlineImage } from './inline-image';
import { MarkdownList } from './markdown-list';

// `<strong>`'s UA default `font-weight: bolder` is RELATIVE — inside
// `font-light` (300) copy it computes to 400 and the bold is invisible. An
// explicit weight keeps `**bold**` legible everywhere; `bold` (700) matches
// what normal-weight body copy already computed, and tenants can tune it.
const DEFAULT_STRONG_STYLE: CSSProperties = {
  fontWeight: 'var(--pb-strong-weight, bold)' as CSSProperties['fontWeight'],
};

export type RichTextOptions = {
  /**
   * Render `[label](href)` as real anchors (default). Pass `false` where the
   * output already lives inside an interactive element (`<a>`, `<button>`,
   * `<summary>`) — nested anchors are invalid HTML and browsers split them.
   *
   * With `false` a link renders as its LABEL TEXT and the href is DROPPED
   * silently. That is the only sane rendering inside an anchor, but it means
   * body-copy call sites (card bodies, action-list descriptions, FAQ answers
   * that live inside a link) cannot carry their own links — prefer moving
   * such copy outside the interactive element if the destination matters.
   * Those fields say "links not supported here" in their Puck label.
   *
   * Either way links are split out before emphasis is tokenized, so emphasis
   * that STRADDLES a link (`**bold [x](/y) more**`) can't pair up and its
   * markers stay literal. Wrap the emphasis inside the label instead.
   */
  allowLinks?: boolean;
  /** Override the `<em>` produced by `*x*` (AccentText's tenant accent). */
  renderEm?: (content: string, key: string) => ReactNode;
  /**
   * Override the `<strong>` produced by `**x**`. Display headings need this:
   * a bare `<strong>`'s `font-weight: bolder` is RELATIVE, so inside a
   * `font-light` (300) heading it computes to 400 and looks unchanged.
   */
  renderStrong?: (content: ReactNode, key: string) => ReactNode;
};

function renderEmphasis(text: string, keyPrefix: string, opts?: RichTextOptions): ReactNode[] {
  const em = opts?.renderEm ?? ((content: string, key: string) => <em key={key}>{content}</em>);
  const strong =
    opts?.renderStrong ??
    ((content: ReactNode, key: string) => (
      <strong key={key} style={DEFAULT_STRONG_STYLE}>
        {content}
      </strong>
    ));
  return parseInlineTokens(text).map((token, i) => {
    const key = `${keyPrefix}-${i}`;
    if (token.type === 'strongem') return strong(em(token.content, `${key}-em`), key);
    if (token.type === 'strong') return strong(token.content, key);
    if (token.type === 'em') return em(token.content, key);
    if (token.type === 'code')
      return (
        // The text colour is explicit, never inherited: on an inverted
        // surface (hero, colored CTA band) the inherited colour is white,
        // which on this light chip is invisible (1.1:1 contrast). Kept as
        // a light/dark class pair rather than a `--pb-*` token because one
        // token cannot carry both themes' values.
        <code
          key={key}
          className="rounded bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-100 px-1.5 py-0.5 text-sm font-mono"
        >
          {token.content}
        </code>
      );
    return token.content;
  });
}

/**
 * Inline markdown → ReactNodes, with links.
 *
 * The shared `parseInlineTokens` covers emphasis/code only, so `[x](y)` used to
 * render as literal text everywhere it was accepted. Anchors carry
 * `--pb-prose-link-color` so a tenant can colour body links (BioGarden's Figma
 * uses the brand purple) without restyling every link on the page.
 */
export function renderRichText(
  text: string | undefined | null,
  opts?: RichTextOptions,
): ReactNode[] {
  // Legacy Puck JSON saved before a field existed passes undefined where the
  // prop type says string; `{prop}` rendered nothing, so render nothing —
  // don't let one missing field throw and blank the whole page.
  if (!text) return [];
  return collapse(renderRichTextNodes(text, opts));
}

/**
 * Multi-node output collapses into ONE `<span>`: many render sites are flex
 * containers (`inline-flex gap-2` labels, `justify-between` summaries), where
 * each node would otherwise become its own flex item and `gap` would scatter
 * the fragments. Plain text stays a bare string — single-node output is
 * returned as-is, so unmarked copy renders byte-identically to before.
 */
function collapse(nodes: ReactNode[]): ReactNode[] {
  if (nodes.length <= 1) return nodes;
  return [<span key="rt">{nodes}</span>];
}

function renderRichTextNodes(text: string, opts?: RichTextOptions): ReactNode[] {
  const linksAllowed = opts?.allowLinks !== false;
  return splitLinks(text).flatMap((segment, i): ReactNode[] => {
    if (segment.type === 'image') return [renderInlineImage(segment, `i-${i}`)];
    if (segment.type === 'linkedImage') {
      const image = renderInlineImage(segment, `i-${i}`);
      return [linksAllowed ? anchor(segment.href, image, `l-${i}`) : image];
    }
    if (segment.type === 'link') {
      // Inside an `<a>`/`<button>`/`<summary>` an anchor can't be nested, so
      // keep the label (emphasis and all) and drop the href — showing the
      // raw `[label](href)` markup reads as broken copy to editors.
      if (!linksAllowed) return renderEmphasis(segment.label, `u-${i}`, opts);
      return [anchor(segment.href, renderEmphasis(segment.label, `l-${i}`, opts), `l-${i}`)];
    }
    return renderEmphasis(segment.text, `t-${i}`, opts);
  });
}

function anchor(href: string, children: ReactNode, key: string): ReactNode {
  // Scheme-relative `//host/...` is off-site too — it must get the
  // same new-tab + noopener treatment as absolute http(s) links.
  const external = /^(?:https?:)?\/\//.test(href);
  return (
    <a
      key={key}
      href={href}
      className="underline underline-offset-2 text-[color:var(--pb-prose-link-color,inherit)]"
      {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
    >
      {children}
    </a>
  );
}

export type RichTextBlockProps = {
  text: string | undefined;
  className?: string;
  style?: CSSProperties;
};

/**
 * Block-level light markdown for `textarea` widget fields: blank-line
 * paragraphs, `- ` / `1. ` lists, and everything `renderRichText` does inline.
 *
 * Single-paragraph content (the common case) renders the same `<p>` the
 * widget rendered before — zero DOM/visual change for plain text. Multi-block
 * content wraps in a `<div>` carrying the caller's className/style so the
 * widget's spacing and typography still apply.
 *
 * Heading markers (`#`) are demoted to bold paragraphs on purpose: widget
 * copy must not inject `<h1>`–`<h3>` and break the page's real heading
 * hierarchy — full headings stay the job of the Markdown widget and Heading
 * fields.
 */
export function RichTextBlock({ text, className, style }: RichTextBlockProps): ReactNode {
  // softBreaks: several widget textareas rendered with `whitespace-pre-line`
  // before markdown support, so a bare newline has always been a visible
  // line break there — keep that meaning instead of markdown's space-join.
  const blocks = parseMarkdownBlocks(text ?? '', { softBreaks: true });
  if (blocks.length === 0) return null;
  const only = blocks.length === 1 ? blocks[0] : undefined;
  // `break-words`: a long URL is one unbreakable word, and in a narrow column
  // (DefinitionList, Section intro) it widened the page instead of wrapping.
  const wrapperClass = cn('break-words', className);
  if (only && only.type === 'p') {
    return (
      <p className={wrapperClass} style={style}>
        {renderWithSoftBreaks(only.text)}
      </p>
    );
  }
  return (
    <div className={wrapperClass} style={style}>
      {blocks.map((block, i) => renderBlock(block, i))}
    </div>
  );
}

/** Inline rich text where remaining `\n`s (softBreaks parsing) become `<br/>`. */
function renderWithSoftBreaks(text: string): ReactNode[] {
  return text.split('\n').flatMap((line, i) => {
    // Each line's nodes go in a keyed fragment so renderRichText's
    // per-line keys ("t-0", ...) can't collide across lines.
    //
    // Index is the only identity these have: they're positional slices of one
    // string, re-derived on every render, with nothing stable to key on.
    // biome-ignore lint/suspicious/noArrayIndexKey: positional slices of a string have no stable id
    const nodes = <Fragment key={`ln-${i}`}>{renderRichText(line)}</Fragment>;
    // biome-ignore lint/suspicious/noArrayIndexKey: same — the <br> is positional too
    return i === 0 ? [nodes] : [<br key={`br-${i}`} />, nodes];
  });
}

function renderBlock(block: MarkdownBlock, key: number): ReactNode {
  if (block.type === 'ul' || block.type === 'ol') {
    return <MarkdownList key={key} list={block} className="pl-5 [&:not(:first-child)]:mt-3" />;
  }
  return (
    <p
      key={key}
      className={cn('[&:not(:first-child)]:mt-3', block.type !== 'p' && 'font-semibold')}
    >
      {renderWithSoftBreaks(block.text)}
    </p>
  );
}
