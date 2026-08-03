/** The text column of the media-object widget — eyebrow, heading, body,
 *  bullets, footnote and link. Split out so the render file stays under
 *  the 300-line cap. */

import type { CSSProperties } from 'react';

import { cn } from '../../utils/widgetUtils';
import { AccentText } from './_internal/accent-text';
import { LinkArrow } from './_internal/link-arrow';
import { RichTextBlock, renderRichText } from './_internal/rich-text';
import { CTAButton, eyebrowTextStyle, maskStyle } from './_shared';
import { GRID_TEXT, headingStyle, type MediaObjectWidgetProps } from './media-object-layout';

type TextBlockProps = MediaObjectWidgetProps & {
  isDark: boolean;
  grid: boolean;
  textMax: string;
};

export function MediaObjectText({
  eyebrow = '',
  datePill = '',
  datePillColor = '',
  heading,
  body,
  bodyMaxWidth = '',
  bullets = [],
  bulletSize = 'md',
  bulletMarker = 'square',
  footnote = '',
  linkLabel,
  linkHref,
  linkVariant = 'link',
  logos,
  headingWidth = 'auto',
  layout = 'half',
  isDark,
  grid,
  textMax,
}: TextBlockProps) {
  return (
    <>
      {/* The banner layout renders the eyebrow in its own grid column, so
				    only the other layouts carry it inline above the heading (the
				    BioGarden "VIELFÄLTIGE GÄRTEN" kicker). */}
      {eyebrow && layout !== 'banner' && (
        <p
          style={{
            ...eyebrowTextStyle(),
            color: isDark
              ? 'var(--pb-surface-contrast, #ffffff)'
              : 'var(--pb-heading-color, #161728)',
          }}
        >
          {renderRichText(eyebrow)}
        </p>
      )}
      {datePill && (
        <span
          className="inline-flex w-fit items-center rounded-full px-3 py-1 text-sm font-bold"
          style={{
            backgroundColor: datePillColor || 'var(--pb-accent, #16a34a)',
            color: 'var(--pb-surface-contrast, #ffffff)',
          }}
        >
          {renderRichText(datePill)}
        </span>
      )}
      {heading && (
        <h3
          className={cn('leading-tight', headingWidth === 'narrow' && 'max-w-[400px]')}
          style={headingStyle(isDark, layout)}
        >
          <AccentText text={heading} />
        </h3>
      )}
      {body && (
        <RichTextBlock
          text={body}
          className={cn(
            'whitespace-pre-line text-lg leading-[var(--pb-body-leading,1.625)]',
            isDark && 'opacity-80',
          )}
          style={{
            color: isDark ? 'var(--pb-surface-contrast, #ffffff)' : 'var(--pb-body-color)',
            maxWidth: bodyMaxWidth || undefined,
          }}
        />
      )}
      {footnote && (
        <p
          className={cn(
            'font-semibold italic leading-[var(--pb-body-leading,1.625)]',
            isDark && 'opacity-80',
          )}
          style={{
            color: isDark ? 'var(--pb-surface-contrast, #ffffff)' : 'var(--pb-body-color)',
          }}
        >
          {renderRichText(footnote)}
        </p>
      )}
      {bullets.filter((b) => b.title || b.body).length > 0 && (
        // The design's point list: a small square marker, a Medium point
        // title, and an optional explanation line beneath it.
        <ul className="flex list-none flex-col gap-6 pt-2">
          {bullets
            .filter((b) => b.title || b.body)
            .map((point, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; card content repeats, so a content key collides
              <li key={i} className="flex gap-3">
                {bulletMarker === 'square' && (
                  <span
                    aria-hidden="true"
                    className="mt-[0.55em] size-[7px] shrink-0 bg-current"
                    style={{
                      color: isDark
                        ? 'var(--pb-surface-contrast, #ffffff)'
                        : 'var(--pb-heading-color, #161728)',
                    }}
                  />
                )}
                <div className="flex flex-col gap-2">
                  {point.title && (
                    <p
                      className={cn(
                        'font-medium leading-tight',
                        bulletSize === 'lg' ? 'text-[24px]' : 'text-[20px]',
                      )}
                      style={{
                        color: isDark
                          ? 'var(--pb-surface-contrast, #ffffff)'
                          : 'var(--pb-heading-color, #161728)',
                      }}
                    >
                      {renderRichText(point.title)}
                    </p>
                  )}
                  {point.body && (
                    <RichTextBlock
                      text={point.body}
                      className="whitespace-pre-line leading-[var(--pb-body-leading,1.625)]"
                      style={{
                        color: isDark
                          ? 'var(--pb-surface-contrast, #ffffff)'
                          : 'var(--pb-body-color)',
                        opacity: isDark ? 0.8 : 1,
                      }}
                    />
                  )}
                </div>
              </li>
            ))}
        </ul>
      )}
      {linkLabel && linkVariant === 'button' && (
        <div className="pt-2">
          <CTAButton
            label={linkLabel}
            href={linkHref || '#'}
            variant={isDark ? 'inverse-outline' : 'secondary'}
          />
        </div>
      )}
      {linkLabel &&
        linkVariant === 'link' &&
        (isDark ? (
          <a
            href={linkHref || '#'}
            className="inline-flex items-center gap-1 font-medium hover:opacity-80"
            style={{ color: 'var(--pb-surface-contrast, #ffffff)' }}
          >
            {renderRichText(linkLabel, { allowLinks: false })}
            <LinkArrow className="size-5" />
          </a>
        ) : (
          <a
            href={linkHref || '#'}
            className="inline-flex items-center gap-1 font-medium text-[color:var(--pb-link-color,var(--pb-accent,#2f7d32))] hover:text-[color:var(--pb-link-hover-color,var(--pb-link-color,var(--pb-accent,#2f7d32)))] hover:[text-decoration-line:var(--pb-link-hover-decoration,underline)]"
          >
            {renderRichText(linkLabel, { allowLinks: false })}
            <LinkArrow className="size-5" />
          </a>
        ))}
      {logos && logos.filter((l) => l.src).length > 0 && (
        <div className="flex flex-wrap items-center gap-6 pt-2">
          {logos
            .filter((l) => l.src)
            .map((logo, i) => (
              <img
                // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; card content repeats, so a content key collides
                key={i}
                src={logo.src}
                alt={logo.alt}
                className="h-12 w-auto object-contain"
              />
            ))}
        </div>
      )}
    </>
  );
}
