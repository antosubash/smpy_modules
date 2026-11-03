/** MediaObject render. The props type and layout tables live in
 *  media-object-layout.ts so this file stays under the 300-line cap. */

/** MediaObjectWidget types, helpers and render — split from media-object-widget.tsx,
 *  which keeps the field definitions, so both stay under the 300-line cap. */

import { cn } from '../../utils/widgetUtils';
import { renderRichText } from './_internal/rich-text';
import { maskStyle, SIZES_HALF, srcsetAttrs } from './_shared';

import type { MediaObjectWidgetProps } from './media-object-layout';

export type { MediaObjectWidgetProps } from './media-object-layout';

export function MediaObjectImage({
  imageUrl,
  imageAlt,
  imageSrcset = '',
  imageMaskUrl = '',
  imageShape = 'rounded',
  imageTag = '',
  imageTagColor = '',
  imageTagMaskUrl = '',
  imageTagImageUrl = '',
  heading,
}: MediaObjectWidgetProps) {
  // Supplied cut-out wins over a mask: the artwork already has the shape, so
  // it renders untouched. A mask is the fallback for square source images.
  const native = imageShape === 'native';
  const masked = !native && Boolean(imageMaskUrl);
  const imageEl = imageUrl ? (
    <img
      src={imageUrl}
      {...srcsetAttrs(imageSrcset, SIZES_HALF)}
      alt={imageAlt || heading}
      loading="lazy"
      className={cn('w-full h-auto', !masked && !native && 'rounded-lg')}
      style={masked ? maskStyle(imageMaskUrl) : undefined}
    />
  ) : (
    <div
      className={cn(
        'w-full aspect-square bg-gradient-to-br from-gray-200 to-gray-300',
        !masked && !native && 'rounded-lg',
      )}
      style={masked ? maskStyle(imageMaskUrl) : undefined}
    />
  );
  return imageTag ? (
    <div className="relative">
      {imageEl}
      {imageTagImageUrl ? (
        // Supplied tag artwork: the file carries the shape AND the colour,
        // so only the upright label is drawn over it. No colour behind it
        // for the same reason as the timeline blob — the artwork is a
        // transparent cut-out, and a backing colour would square off the
        // tilted tag shape.
        <span className="pointer-events-none absolute -top-4 -left-3 block w-[34%] max-w-[188px]">
          <img
            src={imageTagImageUrl}
            alt=""
            aria-hidden="true"
            loading="lazy"
            className="block h-auto w-full"
          />
          <span
            className="absolute inset-0 flex items-center justify-center px-2 text-center text-[20px] font-bold leading-tight"
            style={{ color: 'var(--pb-surface-contrast, #ffffff)' }}
          >
            {renderRichText(imageTag)}
          </span>
        </span>
      ) : imageTagMaskUrl ? (
        // Figma tag: a tilted blob straddling the photo's top-left corner
        // with an upright label over it (same two-layer construction the
        // timeline marker uses — the art rotates, the text does not).
        <span
          className="pointer-events-none absolute -top-4 -left-3 block w-[34%] max-w-[188px]"
          style={{ aspectRatio: '188 / 161' }}
        >
          <span
            aria-hidden="true"
            className="absolute inset-0"
            style={{
              backgroundColor: imageTagColor || 'var(--pb-accent, #16a34a)',
              transform: 'rotate(-18.2deg)',
              ...maskStyle(imageTagMaskUrl),
            }}
          />
          <span
            className="absolute inset-0 flex items-center justify-center px-2 text-center text-[20px] font-bold leading-tight"
            style={{ color: 'var(--pb-surface-contrast, #ffffff)' }}
          >
            {renderRichText(imageTag)}
          </span>
        </span>
      ) : (
        <span
          className="absolute left-4 top-6 inline-flex items-center rounded-full px-4 py-1.5 text-sm font-bold"
          style={{
            backgroundColor: imageTagColor || 'var(--pb-accent, #16a34a)',
            color: 'var(--pb-surface-contrast, #ffffff)',
          }}
        >
          {renderRichText(imageTag)}
        </span>
      )}
    </div>
  ) : (
    imageEl
  );
}
