/** FAQ types, styles and render — split from faq-widget.tsx, which keeps the
 *  field definitions, so both stay under the 300-line cap. */

import type { CSSProperties } from 'react';

import { parseMarkdownBlocks } from '../../utils/markdown';
import { cn } from '../../utils/widgetUtils';
import { AccentText } from './_internal/accent-text';
import { DisclosureChevron } from './_internal/disclosure-chevron';
import { RichTextBlock, renderRichText } from './_internal/rich-text';
import { eyebrowTextStyle } from './_shared';

export type FaqItem = {
  question: string;
  answer: string;
};

export type FaqWidgetProps = {
  eyebrow: string;
  title: string;
  /** Optional paragraph under the title (2-column layout only). */
  lead?: string;
  variant: 'cards' | 'divider';
  /** "muted" wraps the 2-column layout in a soft rounded card (Mowing FAQs). */
  surface?: 'default' | 'muted';
  /**
   * Optional CSS color for the 2-column band background (e.g. a tenant's
   * program color). When set, the band renders with white text and rules.
   */
  surfaceColor?: string;
  items: FaqItem[];
};

const DISPLAY_STYLE: CSSProperties = {
  fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
  letterSpacing: 'var(--pb-display-tracking)',
  fontFamily: 'var(--pb-display-font)',
  color: 'var(--pb-heading-color)',
};

// Section heading size: reads `--pb-heading-md` (Mowing → 40px to match the
// Figma) and falls back to the prior responsive scale (~30→48px) so tenants
// that don't set the token (GCA, Recodo) render unchanged.
const HEADING_STYLE: CSSProperties = {
  ...DISPLAY_STYLE,
  fontSize: 'var(--pb-heading-md, clamp(1.875rem, 1.3rem + 2.2vw, 3rem))',
};

/** An answer is light markdown: links, `- ` bullets and `**bold**`. */
function Answer({ text, inverse }: { text: string; inverse?: boolean }) {
  return (
    <div
      className="pb-5 leading-[var(--pb-body-leading,1.625)]"
      style={
        inverse
          ? { color: 'var(--pb-surface-contrast, #ffffff)', opacity: 0.85 }
          : { color: 'var(--pb-body-color)' }
      }
    >
      {parseMarkdownBlocks(text || '').map((block, i) =>
        block.type === 'ul' ? (
          // biome-ignore lint/suspicious/noArrayIndexKey: blocks are positional slices of one string, re-derived each render
          <ul key={i} className="list-disc pl-5 [&:not(:first-child)]:mt-3">
            {block.items.map((li, j) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: list items are positional slices too
              <li key={j}>{renderRichText(li)}</li>
            ))}
          </ul>
        ) : (
          // biome-ignore lint/suspicious/noArrayIndexKey: blocks are positional slices of one string, re-derived each render
          <p key={i} className="[&:not(:first-child)]:mt-3">
            {renderRichText(block.text)}
          </p>
        ),
      )}
    </div>
  );
}

// Divider-row accordion (thin top/bottom rules, +/- toggle) — the GCA style,
// shared by the 2-column (our-process) and single-column (FAQs / statements)
// layouts.
function DividerItems({ items, inverse = false }: { items: FaqItem[]; inverse?: boolean }) {
  return (
    <div
      className={cn(
        'border-t-[length:var(--pb-accordion-top-rule,1px)]',
        inverse ? 'border-white/30' : 'border-[#1a353e]/15',
      )}
    >
      {items?.map((item, idx) => (
        // Keyed on the question so reordering in the editor carries each row's
        // open/closed state with it; the index is only a fallback for a blank one.
        <details
          key={item.question || `faq-${idx}`}
          className={cn('group border-b', inverse ? 'border-white/30' : 'border-[#1a353e]/15')}
        >
          <summary
            className="flex cursor-pointer list-none items-center justify-between gap-4 py-4 text-lg font-semibold"
            style={{
              color: inverse ? 'var(--pb-surface-contrast, #ffffff)' : 'var(--pb-heading-color)',
            }}
          >
            {/* Inside <summary>: emphasis only — a nested anchor here would
                be invalid HTML and hijack the toggle. */}
            {renderRichText(item.question || '', { allowLinks: false })}
            <span
              aria-hidden="true"
              className={cn(
                'shrink-0 text-2xl font-light leading-none',
                !inverse && 'text-[#1a353e]',
              )}
              style={inverse ? { color: 'var(--pb-surface-contrast, #ffffff)' } : undefined}
            >
              <span className="group-open:hidden">+</span>
              <span className="hidden group-open:inline">−</span>
            </span>
          </summary>
          <Answer text={item.answer} inverse={inverse} />
        </details>
      ))}
    </div>
  );
}

/** Figma 2-column layout: eyebrow left, heading + divider accordion right. */
function SplitFaq({
  eyebrow,
  title,
  lead,
  surface,
  surfaceColor,
  items,
}: Required<Pick<FaqWidgetProps, 'eyebrow' | 'title' | 'items'>> &
  Pick<FaqWidgetProps, 'lead' | 'surface' | 'surfaceColor'>) {
  const muted = surface === 'muted';
  const inverse = !!surfaceColor;
  return (
    <section className="container mx-auto px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8">
      <div
        className={cn(
          'grid gap-8 lg:grid-cols-[var(--pb-split-cols,1fr_2fr)] lg:gap-[var(--pb-split-gap,3rem)]',
          muted &&
            !inverse &&
            'rounded-[12px] bg-[var(--pb-surface-muted,#f3f3f4)] px-8 py-12 lg:px-0 lg:py-20',
          inverse && 'rounded-[12px] px-8 py-12 lg:px-0 lg:py-20',
        )}
        style={inverse ? { backgroundColor: surfaceColor } : undefined}
      >
        <p
          className={cn((muted || inverse) && 'lg:pl-12')}
          style={{
            // Eyebrow size/weight/case/tracking are theme-driven; the
            // fallbacks keep today's look for tenants that don't set them.
            ...eyebrowTextStyle('1.125rem', '400'),
            color: inverse
              ? 'var(--pb-surface-contrast, #ffffff)'
              : 'var(--pb-heading-color,#161728)',
          }}
        >
          {renderRichText(eyebrow)}
        </p>
        <div className="max-w-[var(--pb-split-content-max,none)]">
          <div className="max-w-[var(--pb-faq-intro-max,none)]">
            {/* AccentText, not bare renderRichText: these are display headings
                on `--pb-display-weight`, where a plain <strong>'s relative
                `bolder` can compute to no visible change. */}
            {title && (
              <h2
                className="mb-8 leading-tight"
                style={
                  inverse
                    ? { ...HEADING_STYLE, color: 'var(--pb-surface-contrast, #ffffff)' }
                    : HEADING_STYLE
                }
              >
                <AccentText text={title} />
              </h2>
            )}
            {lead && (
              <RichTextBlock
                text={lead}
                className="-mt-4 mb-8 text-lg leading-[var(--pb-body-leading,1.625)]"
                style={
                  inverse
                    ? { color: 'var(--pb-surface-contrast, #ffffff)', opacity: 0.85 }
                    : { color: 'var(--pb-body-color)' }
                }
              />
            )}
          </div>
          <DividerItems items={items} inverse={inverse} />
        </div>
      </div>
    </section>
  );
}

export function FaqRender({
  eyebrow,
  title,
  lead = '',
  variant = 'cards',
  surface = 'default',
  surfaceColor = '',
  items,
}: FaqWidgetProps) {
  // The 2-column layout is opt-in via `eyebrow`.
  if (eyebrow) {
    return (
      <SplitFaq
        eyebrow={eyebrow}
        title={title}
        lead={lead}
        surface={surface}
        surfaceColor={surfaceColor}
        items={items}
      />
    );
  }

  // Single narrow-column divider accordion (FAQs / statements pages — the page
  // hero already supplies the title, so this is usually just the list).
  if (variant === 'divider') {
    return (
      <section className="container mx-auto max-w-3xl px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8">
        {title && (
          <h2 className="mb-8 leading-tight" style={HEADING_STYLE}>
            <AccentText text={title} />
          </h2>
        )}
        <DividerItems items={items} />
      </section>
    );
  }

  return (
    <div className="container mx-auto px-4 py-[var(--pb-section-py,3rem)] max-w-3xl">
      {title && (
        <h2 className="text-3xl sm:text-4xl lg:text-5xl text-center mb-10" style={DISPLAY_STYLE}>
          <AccentText text={title} />
        </h2>
      )}
      <div className="space-y-3">
        {items?.map((item, idx) => (
          <details
            key={item.question || `faq-card-${idx}`}
            className="group rounded-lg border bg-white dark:bg-gray-900 p-4"
          >
            <summary
              className="cursor-pointer flex items-center justify-between text-lg font-semibold list-none"
              style={{ color: 'var(--pb-heading-color)' }}
            >
              {renderRichText(item.question || '', { allowLinks: false })}
              <DisclosureChevron />
            </summary>
            {/* Same light markdown as the divider variant's answers. */}
            <RichTextBlock
              text={item.answer}
              className="mt-3 leading-[var(--pb-body-leading,1.625)]"
              style={{ color: 'var(--pb-body-color)' }}
            />
          </details>
        ))}
      </div>
    </div>
  );
}
