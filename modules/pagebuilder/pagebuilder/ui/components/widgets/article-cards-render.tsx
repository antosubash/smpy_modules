/** ArticleCards presentation, split from its Puck config so another module
 *  can render the same grid from live data — the news feed does.
 *  The config lives in article-cards-widget.tsx. */

import type { CSSProperties } from 'react';
import { cn } from '../../utils/widgetUtils';
import { renderRichText } from './_internal/rich-text';
import { TextLink } from './_shared/text-link';

export type ArticleCardItem = {
  imageUrl: string;
  imageAlt: string;
  eyebrow: string;
  date: string;
  title: string;
  body: string;
  href: string;
};

export type ArticleCardsWidgetProps = {
  title: string;
  viewAllLabel: string;
  viewAllHref: string;
  columns: '2' | '3' | '4';
  items: ArticleCardItem[];
};

const COLS_CLASS: Record<ArticleCardsWidgetProps['columns'], string> = {
  '2': 'sm:grid-cols-2',
  '3': 'sm:grid-cols-2 lg:grid-cols-3',
  '4': 'sm:grid-cols-2 lg:grid-cols-4',
};

// Display tokens come from the per-tenant page-builder theme (see styles.css
// `:root` for Recodo defaults and `.gca-root` for the GCA overrides). The
// fallback clamp reproduces the prior `text-2xl sm:text-3xl lg:text-4xl`
// steps: 24px on phones, 30px at 640px, 36px at 1024px. All style objects are
// hoisted — constant tokens only, no per-render allocation.
const HEADING_STYLE: CSSProperties = {
  fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
  letterSpacing: 'var(--pb-display-tracking)',
  fontFamily: 'var(--pb-display-font)',
  color: 'var(--pb-heading-color)',
  fontSize: 'var(--pb-heading-lg, clamp(1.5rem, 1.25rem + 1.5625vw, 2.25rem))',
};

const CARD_META_STYLE: CSSProperties = {
  color: 'var(--pb-body-color)',
  fontSize: 'var(--pb-card-meta-size, 0.75rem)',
};

const CARD_TITLE_STYLE: CSSProperties = {
  fontFamily: 'var(--pb-display-font)',
  fontWeight:
    'var(--pb-card-title-weight, var(--pb-display-weight))' as CSSProperties['fontWeight'],
  fontSize: 'var(--pb-card-title-size, 1.125rem)',
  color: 'var(--pb-heading-color)',
};

const CARD_BODY_STYLE: CSSProperties = {
  color: 'var(--pb-body-color)',
  fontSize: 'var(--pb-card-body-size, 0.875rem)',
};

export function ArticleCardsGrid({
  title,
  viewAllLabel,
  viewAllHref,
  columns,
  items,
}: ArticleCardsWidgetProps) {
  return (
    <section className="container mx-auto px-4 py-12 sm:px-6 lg:px-8">
      {(title || (viewAllLabel && viewAllHref)) && (
        <div className="mb-8 flex items-end justify-between gap-4">
          {title && (
            <h2 className="leading-[var(--pb-heading-leading,1.15)]" style={HEADING_STYLE}>
              {renderRichText(title)}
            </h2>
          )}
          {viewAllLabel && viewAllHref && <TextLink label={viewAllLabel} href={viewAllHref} />}
        </div>
      )}
      <div className={cn('grid gap-6 grid-cols-1', COLS_CLASS[columns])}>
        {items?.map((item, idx) => (
          // The whole card is one anchor, so every string inside it renders
          // with `allowLinks: false` — a nested <a> is invalid HTML and
          // browsers split the card link in two.
          <a
            // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; card content repeats, so a content key collides
            key={idx}
            href={item.href || '#'}
            className="group block"
          >
            <div className="relative aspect-[16/10] overflow-hidden rounded-xl bg-[var(--pb-surface-muted)]">
              {item.imageUrl && (
                <img
                  src={item.imageUrl}
                  alt={item.imageAlt || item.title}
                  loading="lazy"
                  className="size-full object-cover transition-transform duration-300 group-hover:scale-105"
                />
              )}
              {item.eyebrow && (
                <span className="absolute right-3 top-3 inline-flex w-fit items-center rounded-full bg-[var(--pb-card-tag-bg,rgb(255_255_255/0.9))] px-2.5 py-0.5 text-xs font-medium text-[var(--pb-card-tag-color,#1a353e)] backdrop-blur-sm">
                  {renderRichText(item.eyebrow, { allowLinks: false })}
                </span>
              )}
            </div>
            <div className="mt-4">
              {item.date && (
                <span style={CARD_META_STYLE}>
                  {renderRichText(item.date, { allowLinks: false })}
                </span>
              )}
              {item.title && (
                <h3 className="mt-3 leading-snug" style={CARD_TITLE_STYLE}>
                  {renderRichText(item.title, { allowLinks: false })}
                </h3>
              )}
              {item.body && (
                <p className="mt-2 leading-relaxed" style={CARD_BODY_STYLE}>
                  {renderRichText(item.body, { allowLinks: false })}
                </p>
              )}
            </div>
          </a>
        ))}
      </div>
    </section>
  );
}
