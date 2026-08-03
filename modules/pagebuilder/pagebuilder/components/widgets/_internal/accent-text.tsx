import { type CSSProperties, type ReactNode, useMemo } from 'react';
import { renderRichText } from './rich-text';

// Accent word styling is tenant-themeable: Recodo/GCA keep the italic semibold
// default; tenants like Mowing render an upright bold word via these tokens.
const ACCENT_WORD_STYLE: CSSProperties = {
  fontStyle: 'var(--pb-accent-word-style, italic)',
  fontWeight: 'var(--pb-accent-word-weight, 600)' as CSSProperties['fontWeight'],
};

// `<strong>`'s default `font-weight: bolder` is RELATIVE — inside a
// `font-light` (300) display heading it computes to 400 and looks unchanged,
// so heading bolds carry an explicit tenant-tunable weight.
const STRONG_STYLE: CSSProperties = {
  fontWeight: 'var(--pb-strong-weight, 600)' as CSSProperties['fontWeight'],
};

/**
 * Renders a heading-style string as light markdown. `*word*` segments keep
 * the signature accent treatment — italic semibold by default ("*Clusters*",
 * "*Finder*", "*biodiversity*") — and `**bold**`, `` `code` `` and
 * `[label](href)` render like every other rich-text site.
 */
export function AccentText({
  text,
  color,
  allowLinks,
}: {
  text: string;
  /**
   * Colour for the emphasised segments. Omitted, they inherit — which is what
   * headings want. A section can opt into a contrasting accent (BioGarden's
   * "Offene Fragen" highlights phrases in the brand red) without turning every
   * accent word on the page that colour.
   */
  color?: string;
  /** Pass `false` when the accent text sits inside an `<a>`/`<button>`. */
  allowLinks?: boolean;
}): ReactNode {
  return useMemo(() => {
    if (!text) return null;
    return renderRichText(text, {
      allowLinks,
      renderEm: (content, key) => (
        <em
          key={key}
          className="font-semibold italic"
          style={color ? { ...ACCENT_WORD_STYLE, color } : ACCENT_WORD_STYLE}
        >
          {content}
        </em>
      ),
      renderStrong: (content, key) => (
        <strong key={key} style={STRONG_STYLE}>
          {content}
        </strong>
      ),
    });
  }, [text, color, allowLinks]);
}
