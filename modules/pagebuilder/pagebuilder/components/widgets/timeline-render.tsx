/** Timeline render — both the default "rows" list and the "blobs" variant.
 *  Field definitions live in timeline-widget.tsx. */

import type { CSSProperties } from 'react';
import { cn } from '../../utils/widgetUtils';
import { AccentText } from './_internal/accent-text';
import { RichTextBlock, renderRichText } from './_internal/rich-text';
import { eyebrowTextStyle, maskStyle } from './_shared';

import { MARKER_BLOB, type TimelineItem, type TimelineWidgetProps } from './timeline-layout';

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
  // Blobs: a row of organic coloured shapes (BioGarden "Projekt-Fahrplan").
  // The blob content (marker pill, title, body) is centred and inverse; an
  // empty mask falls back to a plain ellipse so the layout still reads.
  if (variant === 'blobs') {
    const markerMaskCss = markerMaskUrl ? maskStyle(markerMaskUrl) : undefined;
    // Per-entry shape, falling back to the section-wide mask. Built once
    // per distinct url rather than per item so mapped entries sharing a
    // shape share one style object.
    const maskCache = new Map<string, ReturnType<typeof maskStyle>>();
    const maskFor = (it: TimelineItem) => {
      const url = it.shapeMaskUrl || blobMaskUrl;
      if (!url) return undefined;
      let css = maskCache.get(url);
      if (!css) {
        css = maskStyle(url);
        maskCache.set(url, css);
      }
      return css;
    };
    return (
      <section className="container mx-auto px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8">
        {/* Eyebrow in the left margin, title starting at a fixed page-grid line —
					    `--pb-timeline-cols` (BioGarden Figma: the title begins at the grid's
					    3rd edge, 228px into the 1344px content box). The fallback reproduces
					    the previous inline eyebrow-then-title row. */}
        <div className="mb-10 flex flex-col gap-2 sm:grid sm:grid-cols-[var(--pb-timeline-cols,max-content_1fr)] sm:items-baseline sm:gap-x-[var(--pb-timeline-gap,2rem)]">
          {eyebrow && (
            <p
              style={{
                ...eyebrowTextStyle(),
                // This call site's previous literal was `uppercase
                // tracking-wide` UNCONDITIONALLY, unlike the other
                // eyebrows. `eyebrowTextStyle`'s shared fallbacks are
                // `none`/`normal`, so without restating them here a
                // tenant that hasn't opted into uppercase eyebrows would
                // silently get sentence case where it never could before.
                textTransform:
                  'var(--pb-eyebrow-transform, uppercase)' as CSSProperties['textTransform'],
                letterSpacing: 'var(--pb-eyebrow-tracking, 0.025em)',
                color: 'var(--pb-heading-color,#161728)',
              }}
            >
              {renderRichText(eyebrow)}
            </p>
          )}
          {title && (
            <h2
              className={cn('leading-tight', !eyebrow && 'sm:col-span-2')}
              style={{
                color: 'var(--pb-heading-color)',
                fontWeight: 'var(--pb-display-weight)',
                fontFamily: 'var(--pb-display-font)',
                fontSize: 'var(--pb-heading-md, clamp(1.875rem, 1.3rem + 1.4vw, 2.5rem))',
              }}
            >
              <AccentText text={title} />
            </h2>
          )}
        </div>
        {/* A uniform gap (no negative margin) keeps the blobs at the Figma's
					    ~415x343 with clear space between them; overlapping them pushed
					    each shape ~13% oversize and made neighbours collide. */}
        <div className="flex flex-wrap justify-center gap-6 lg:flex-nowrap lg:justify-between">
          {items.map((it, idx) => (
            // The marker tag is a SIBLING of the masked blob, never a child:
            // the blob's mask clips its own descendants, and the tag
            // deliberately straddles the blob's edge.
            // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
            <div key={idx} className="relative flex min-w-[360px] flex-1">
              <div
                className={cn(
                  // Text is left-aligned and vertically centred, inset far
                  // enough that the mask's curved edges never cross it (the
                  // design indents ~22% from the blob's left, ~14% right).
                  'flex w-full flex-col items-start justify-center py-16 pr-[14%] pl-[22%] text-left',
                  !maskFor(it) && !it.shapeImageUrl && 'rounded-[50%]',
                )}
                style={
                  it.shapeImageUrl
                    ? {
                        // Supplied artwork carries both the shape and its
                        // fill; the copy simply lays out on top of it.
                        // Deliberately NO backgroundColor here: the artwork is
                        // a transparent cut-out, so a colour behind it would
                        // show through everywhere the PNG is transparent and
                        // the blob would render as a solid rectangle — which
                        // defeats the whole point of supplying the shape.
                        // The trade-off is that a 404 on the artwork paints
                        // nothing; the seed uploads these assets, so a missing
                        // one is a broken seed rather than a per-entry typo.
                        backgroundImage: `url(${it.shapeImageUrl})`,
                        backgroundSize: '100% 100%',
                        backgroundRepeat: 'no-repeat',
                        aspectRatio: '439 / 360',
                        color: 'var(--pb-surface-contrast, #ffffff)',
                      }
                    : {
                        // Fallback keeps the blob (and its forced contrast
                        // text) visible when an editor leaves the color blank.
                        backgroundColor: it.color || 'var(--pb-accent, #16a34a)',
                        aspectRatio: '439 / 360',
                        color: 'var(--pb-surface-contrast, #ffffff)',
                        ...(maskFor(it) ?? {}),
                      }
                }
              >
                {/* The inline pill is the fallback for BOTH overlay forms —
									    without the `markerImageUrl` guard, the documented
									    "artwork replaces mask + colour" configuration (artwork
									    set, mask empty) renders the year twice. */}
                {it.marker && !markerMaskCss && !markerImageUrl && (
                  <span
                    className="mb-3 inline-flex items-center rounded-full bg-white px-4 py-1 text-sm font-bold"
                    style={{ color: 'var(--pb-heading-color,#161728)' }}
                  >
                    {renderRichText(it.marker)}
                  </span>
                )}
                {it.title && <p className="text-xl font-bold">{renderRichText(it.title)}</p>}
                {it.body && (
                  <RichTextBlock text={it.body} className="mt-2 text-sm leading-relaxed" />
                )}
                {it.meta && (
                  <p className="mt-3 text-sm font-bold italic leading-relaxed">
                    {renderRichText(it.meta)}
                  </p>
                )}
              </div>
              {it.marker && markerImageUrl && (
                <span
                  className="pointer-events-none absolute"
                  style={{
                    left: MARKER_BLOB.left,
                    top: MARKER_BLOB.top,
                    width: MARKER_BLOB.width,
                    aspectRatio: MARKER_BLOB.aspect,
                    transform: 'translate(-50%, -50%)',
                  }}
                >
                  {/* Artwork is drawn already tilted, so no rotation here. */}
                  <img
                    src={markerImageUrl}
                    alt=""
                    aria-hidden="true"
                    loading="lazy"
                    className="absolute inset-0 size-full"
                  />
                  <span
                    className="absolute inset-0 flex items-center justify-center px-2 text-center text-[18px] font-bold leading-tight"
                    style={{
                      color: 'var(--pb-timeline-marker-color, #ffffff)',
                    }}
                  >
                    {renderRichText(it.marker)}
                  </span>
                </span>
              )}
              {it.marker && !markerImageUrl && markerMaskCss && (
                <span
                  className="pointer-events-none absolute"
                  style={{
                    left: MARKER_BLOB.left,
                    top: MARKER_BLOB.top,
                    width: MARKER_BLOB.width,
                    aspectRatio: MARKER_BLOB.aspect,
                    transform: 'translate(-50%, -50%)',
                  }}
                >
                  {/* Tilted art layer… */}
                  <span
                    aria-hidden="true"
                    className="absolute inset-0"
                    style={{
                      backgroundColor: markerColor || 'var(--pb-accent, #16a34a)',
                      transform: `rotate(${MARKER_BLOB.rotation})`,
                      ...markerMaskCss,
                    }}
                  />
                  {/* …and an upright label over it, as in the design. */}
                  <span
                    className="absolute inset-0 flex items-center justify-center px-2 text-center text-[18px] font-bold leading-tight"
                    style={{
                      color: 'var(--pb-timeline-marker-color, #ffffff)',
                    }}
                  >
                    {renderRichText(it.marker)}
                  </span>
                </span>
              )}
            </div>
          ))}
        </div>
      </section>
    );
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
