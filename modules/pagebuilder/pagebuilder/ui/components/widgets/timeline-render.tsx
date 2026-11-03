/** Timeline render — both the default "rows" list and the "blobs" variant.
 *  Field definitions live in timeline-widget.tsx. */

import { cn } from '../../utils/widgetUtils';
import { RichTextBlock, renderRichText } from './_internal/rich-text';
import { eyebrowTextStyle } from './_shared';
import { TimelineBlobsRender } from './timeline-blobs-render';
import type { TimelineWidgetProps } from './timeline-layout';

export function TimelineWidgetRender({
  eyebrow,
  title,
  surface = 'default',
  variant = 'rows',
  blobMaskUrl = '',
  markerMaskUrl = '',
  markerImageUrl = '',
  markerColor = '',
  items,
}: TimelineWidgetProps) {
  if (variant === 'blobs') {
    return TimelineBlobsRender({
      eyebrow,
      title,
      surface,
      variant,
      blobMaskUrl,
      markerMaskUrl,
      markerImageUrl,
      markerColor,
      items,
    });
  }

  return (
    <section className="container mx-auto px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8">
      <div
        className={cn(
          'grid gap-y-6 md:grid-cols-[var(--pb-split-cols,1fr_2fr)] md:gap-x-[var(--pb-split-gap,2rem)]',
          surface === 'muted' &&
            'rounded-[12px] bg-[var(--pb-surface-muted,#f3f3f4)] px-8 py-12 lg:px-0 lg:py-20',
        )}
      >
        {eyebrow && (
          <p
            className={cn(surface === 'muted' && 'lg:pl-12')}
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
        <div
          className={cn('max-w-[var(--pb-split-content-max,48rem)]', !eyebrow && 'md:col-span-2')}
        >
          {title && (
            <h2
              className="leading-tight"
              style={{
                color: 'var(--pb-heading-color)',
                fontWeight: 'var(--pb-display-weight)',
                fontFamily: 'var(--pb-display-font)',
                fontSize: 'var(--pb-heading-md, clamp(1.875rem, 1.3rem + 1.4vw, 2.5rem))',
              }}
            >
              {renderRichText(title)}
            </h2>
          )}
          <div className="mt-8">
            {items.map((it, idx) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
              <div key={idx} className="border-b border-[var(--border,#dcdcdf)] py-6 first:pt-0">
                {it.marker && (
                  <p
                    className="text-[1.75rem] font-medium leading-tight"
                    style={{ color: 'var(--pb-heading-color,#161728)' }}
                  >
                    {renderRichText(it.marker)}
                  </p>
                )}
                {it.title && (
                  <p
                    className="mt-2 text-xl font-medium"
                    style={{ color: 'var(--pb-heading-color,#161728)' }}
                  >
                    {renderRichText(it.title)}
                  </p>
                )}
                {it.body && (
                  <RichTextBlock
                    text={it.body}
                    className="mt-3 text-lg leading-[var(--pb-body-leading,1.625)] text-[var(--pb-body-color,#686873)]"
                  />
                )}
                {it.meta && (
                  <p className="mt-2 text-lg font-bold italic leading-[var(--pb-body-leading,1.625)] text-[var(--pb-body-color,#686873)]">
                    {renderRichText(it.meta)}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
