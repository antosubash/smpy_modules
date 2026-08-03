import type { CSSProperties, ReactNode } from 'react';
import { cn } from '../../../utils/widgetUtils';
import { eyebrowTextStyle } from '../_shared';
import { AccentText } from './accent-text';
import { renderRichText } from './rich-text';

const HEADING_STYLE: CSSProperties = {
  fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
  letterSpacing: 'var(--pb-display-tracking)',
  fontFamily: 'var(--pb-display-font)',
  color: 'var(--pb-heading-color)',
  fontSize: 'var(--pb-heading-md, clamp(1.875rem, 1.3rem + 2.2vw, 3rem))',
};

export type EyebrowSplitSectionProps = {
  eyebrow?: string;
  heading?: string;
  /** Wraps the grid in the Mowing muted rounded card. */
  muted?: boolean;
  children: ReactNode;
};

/**
 * Eyebrow-in-left-margin + big heading + content, on the tenant-tunable
 * `--pb-split-cols` grid (Mowing aligns content to the 4th page-grid column).
 * Shared by ProseSection, DefinitionList, and the LogoCloud grid variant, and
 * matches the existing Mowing FAQ 2-column layout so all Mowing sections align.
 */
export function EyebrowSplitSection({
  eyebrow,
  heading,
  muted = false,
  children,
}: EyebrowSplitSectionProps) {
  return (
    <section className="container mx-auto px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8">
      <div
        className={cn(
          'grid gap-8 lg:grid-cols-[var(--pb-split-cols,1fr_2fr)] lg:gap-[var(--pb-split-gap,3rem)]',
          muted &&
            'rounded-[12px] bg-[var(--pb-surface-muted,#f3f3f4)] px-8 py-12 lg:px-0 lg:py-20',
        )}
      >
        {eyebrow && (
          <p
            className={cn(muted && 'lg:pl-12')}
            style={{
              // Eyebrow size/weight/case/tracking are theme-driven; the
              // fallbacks keep today's look for tenants that don't set them.
              ...eyebrowTextStyle('1.125rem', '400'),
              color: 'var(--pb-heading-color,#161728)',
            }}
          >
            {renderRichText(eyebrow)}
          </p>
        )}
        <div className="max-w-[var(--pb-split-content-max,none)]">
          {/* AccentText, not bare renderRichText: this is a display heading on
					    `--pb-display-weight`, where a plain <strong>'s relative `bolder`
					    can compute to no visible change. */}
          {heading && (
            <h2 className="mb-8 leading-tight" style={HEADING_STYLE}>
              <AccentText text={heading} />
            </h2>
          )}
          {children}
        </div>
      </div>
    </section>
  );
}
