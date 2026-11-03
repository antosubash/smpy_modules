/** MediaObject render. The props type and layout tables live in
 *  media-object-layout.ts so this file stays under the 300-line cap. */

/** MediaObjectWidget types, helpers and render — split from media-object-widget.tsx,
 *  which keeps the field definitions, so both stay under the 300-line cap. */

import { cn } from '../../utils/widgetUtils';
import { renderRichText } from './_internal/rich-text';
import { eyebrowTextStyle, srcsetAttrs } from './_shared';

import { GRID_IMAGE, GRID_TEXT, type MediaObjectWidgetProps } from './media-object-layout';
import { MediaObjectText } from './media-object-text';

export type { MediaObjectWidgetProps } from './media-object-layout';

import { MediaObjectImage } from './media-object-image';

export const MediaObjectWidgetRender = ({
  imageUrl,
  imageAlt,
  imageSrcset = '',
  imageMaskUrl = '',
  imageShape = 'rounded',
  imageTag = '',
  imageTagColor = '',
  imageTagMaskUrl = '',
  imageTagImageUrl = '',
  imagePosition,
  eyebrow = '',
  datePill = '',
  datePillColor = '',
  bodyMaxWidth = '',
  footnote = '',
  bullets = [],
  bulletSize = 'md',
  bulletMarker = 'square',
  linkVariant = 'link',
  heading,
  body,
  linkLabel,
  linkHref,
  logos,
  headingWidth = 'auto',
  layout = 'half',
  textWidth = 'auto',
  surface,
  surfaceColor = '',
}: MediaObjectWidgetProps) => {
  const isDark = surface === 'dark' || !!surfaceColor;
  const grid = layout === 'grid';
  // "auto" keeps the legacy unconstrained text; the grid layout needs a
  // concrete column span, so it falls back to the 4-column (~432px) text.
  const widthKey = textWidth === 'auto' ? 'sm' : textWidth;
  const textMax = textWidth === 'auto' ? '' : GRID_TEXT[widthKey].max;

  const textBlock = (
    <MediaObjectText
      {...({
        eyebrow,
        datePill,
        datePillColor,
        heading,
        body,
        bodyMaxWidth,
        bullets,
        bulletSize,
        bulletMarker,
        footnote,
        linkLabel,
        linkHref,
        linkVariant,
        logos,
        headingWidth,
        layout,
      } as MediaObjectWidgetProps)}
      isDark={isDark}
    />
  );

  const image = MediaObjectImage({
    imageUrl,
    imageAlt,
    imageSrcset,
    imageMaskUrl,
    imageShape,
    imageTag,
    imageTagColor,
    imageTagMaskUrl,
    imageTagImageUrl,
    heading,
  } as MediaObjectWidgetProps);

  // Banner: eyebrow in the first grid column, text at the 4th column
  // (Figma "Project Partners": 652px text, logo strip underneath).
  if (layout === 'banner') {
    return (
      <section className="container mx-auto px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8">
        <div
          className={cn(
            'rounded-[12px] px-8 py-12 lg:grid lg:grid-cols-12 lg:gap-6 lg:px-0 lg:py-20',
            isDark && !surfaceColor
              ? 'bg-[var(--secondary,#1a353e)]'
              : surface === 'muted' && !surfaceColor
                ? 'bg-[var(--pb-surface-muted,#f3f3f4)]'
                : '',
          )}
          style={surfaceColor ? { backgroundColor: surfaceColor } : undefined}
        >
          {eyebrow && (
            <p
              className="mb-6 lg:col-span-3 lg:mb-0 lg:pl-12"
              style={{
                ...eyebrowTextStyle('1.125rem', '400'),
                color: isDark ? 'var(--pb-surface-contrast, #ffffff)' : 'var(--pb-heading-color)',
              }}
            >
              {renderRichText(eyebrow)}
            </p>
          )}
          <div className="max-w-[652px] space-y-4 lg:col-start-4 lg:col-span-7">
            {textBlock}
            {imageUrl && (
              <img
                src={imageUrl}
                // Rendered 68px tall — the smallest variant is plenty.
                {...srcsetAttrs(imageSrcset, '320px')}
                alt={imageAlt || heading}
                loading="lazy"
                className="mt-8 h-[68px] w-auto max-w-full object-contain object-left"
              />
            )}
          </div>
        </div>
      </section>
    );
  }

  const layoutBlock = grid ? (
    // 12-col page grid: text and image cells sit on the same columns as the
    // Figma layout, so section text lines up across the whole page. Both
    // cells pin to row 1: the image cell renders first in the DOM, so for
    // image-right (image at col 7, text at col 2) grid auto-placement would
    // otherwise wrap the text cell to a second row instead of beside it.
    <div className="flex flex-col gap-8 lg:grid lg:grid-cols-12 lg:items-center lg:gap-6">
      <div
        className={cn(
          'w-full lg:row-start-1',
          imagePosition === 'right' ? GRID_IMAGE[widthKey].right : GRID_IMAGE[widthKey].left,
        )}
      >
        {image}
      </div>
      <div
        className={cn(
          'space-y-4 lg:row-start-1',
          textMax,
          imagePosition === 'right' ? GRID_TEXT[widthKey].right : GRID_TEXT[widthKey].left,
        )}
      >
        {textBlock}
      </div>
    </div>
  ) : (
    <div
      className={cn(
        'flex flex-col md:flex-row gap-8 lg:gap-12 items-center',
        imagePosition === 'right' ? 'md:flex-row-reverse' : '',
      )}
    >
      <div className="md:w-1/2">{image}</div>
      <div className={cn('md:w-1/2 space-y-4', textMax)}>{textBlock}</div>
    </div>
  );

  if (isDark) {
    return (
      <section className="container mx-auto px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8">
        <div
          className={cn(
            'rounded-[12px]',
            !surfaceColor && 'bg-[var(--secondary,#1a353e)]',
            grid ? 'px-8 py-12 lg:px-0' : 'p-8 lg:p-12',
          )}
          style={surfaceColor ? { backgroundColor: surfaceColor } : undefined}
        >
          {layoutBlock}
        </div>
      </section>
    );
  }

  if (surface === 'muted') {
    return (
      <section className="container mx-auto px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8">
        <div
          className={cn(
            'rounded-[12px] bg-[var(--pb-surface-muted,#f3f3f4)]',
            grid ? 'px-8 py-12 lg:px-0' : 'p-8 sm:p-10 lg:p-14',
          )}
        >
          {layoutBlock}
        </div>
      </section>
    );
  }

  return (
    <section className="container mx-auto px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8">
      {layoutBlock}
    </section>
  );
};
