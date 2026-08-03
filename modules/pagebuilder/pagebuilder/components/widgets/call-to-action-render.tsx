/** CallToActionWidget types, helpers and render — split from call-to-action-widget.tsx,
 *  which keeps the field definitions, so both stay under the 300-line cap. */

import type { CSSProperties } from 'react';
import { RichTextBlock, renderRichText } from './_internal/rich-text';
import { CTAButton, Heading, Section } from './_shared';

export type CtaLink = { label: string; href: string };
export type CtaImage = { src: string; alt: string; caption: string };

export type CallToActionWidgetProps = {
  surface: 'default' | 'lime' | 'soft' | 'related';
  /**
   * Optional CSS color for the band background (e.g. a tenant's program
   * color). When set, renders the centered band on this color with white
   * text, overriding `surface`.
   */
  surfaceColor?: string;
  align: 'left' | 'center';
  eyebrow: string;
  heading: string;
  subheading: string;
  primaryLabel: string;
  primaryHref: string;
  secondaryLabel: string;
  secondaryHref: string;
  links: CtaLink[];
  images: CtaImage[];
};

const DISPLAY_STYLE: CSSProperties = {
  fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
  letterSpacing: 'var(--pb-display-tracking)',
  fontFamily: 'var(--pb-display-font)',
};

// Hoisted band-heading styles (constant tokens only). The fallback clamps
// reproduce the prior `text-2xl sm:text-3xl lg:text-4xl` responsive steps:
// 24px on phones, 30px at 640px, 36px at 1024px.
const SOFT_HEADING_STYLE: CSSProperties = {
  ...DISPLAY_STYLE,
  color: '#1a353e',
  fontSize: 'var(--pb-heading-lg, clamp(1.5rem, 1.25rem + 1.5625vw, 2.25rem))',
};

const LIME_HEADING_STYLE: CSSProperties = {
  ...DISPLAY_STYLE,
  color: '#1a353e',
  fontSize: 'var(--pb-heading-xl, clamp(1.5rem, 1.25rem + 1.5625vw, 2.25rem))',
};

// Inset bands (lime / soft) share one shell so they line up with every other
// contained section at the same content width across breakpoints.
const BAND_SHELL = 'container mx-auto px-4 py-12 sm:px-6 lg:px-8';

export const CallToActionWidgetRender = ({
  surface,
  align,
  eyebrow,
  heading,
  subheading,
  primaryLabel,
  primaryHref,
  secondaryLabel,
  secondaryHref,
  links,
  images,
  surfaceColor = '',
}: CallToActionWidgetProps) => {
  // Custom-colored band (tenant program colors): centered white text on
  // the given background, with the links rendered as white text links.
  if (surfaceColor) {
    return (
      <section className={BAND_SHELL}>
        <div
          className="rounded-3xl px-6 py-12 text-center lg:py-16"
          style={{ backgroundColor: surfaceColor }}
        >
          {eyebrow && (
            <p
              className="text-sm font-medium opacity-80"
              style={{ color: 'var(--pb-surface-contrast, #ffffff)' }}
            >
              {renderRichText(eyebrow)}
            </p>
          )}
          {heading && (
            <h2
              className="mx-auto max-w-3xl text-2xl sm:text-3xl lg:text-4xl"
              style={{
                ...DISPLAY_STYLE,
                color: 'var(--pb-surface-contrast, #ffffff)',
              }}
            >
              {renderRichText(heading)}
            </h2>
          )}
          {subheading && (
            <RichTextBlock
              text={subheading}
              className="mx-auto mt-3 max-w-2xl opacity-85"
              style={{ color: 'var(--pb-surface-contrast, #ffffff)' }}
            />
          )}
          {links && links.length > 0 && (
            <div className="mt-6 flex flex-wrap items-center justify-center gap-x-8 gap-y-3">
              {links.map((link, idx) => (
                <a
                  key={link.href || link.label || `cta-link-${idx}`}
                  href={link.href || '#'}
                  className="text-sm font-semibold underline-offset-4 hover:underline"
                  style={{ color: 'var(--pb-surface-contrast, #ffffff)' }}
                >
                  {renderRichText(link.label || '', { allowLinks: false })}
                </a>
              ))}
            </div>
          )}
          {primaryLabel && (
            <a
              href={primaryHref || '#'}
              className="mt-6 inline-flex items-center justify-center rounded-full border px-6 py-2.5 text-sm font-semibold transition-colors hover:bg-white/10"
              style={{
                color: 'var(--pb-surface-contrast, #ffffff)',
                borderColor: 'var(--pb-surface-contrast, #ffffff)',
              }}
            >
              {renderRichText(primaryLabel, { allowLinks: false })}
            </a>
          )}
        </div>
      </section>
    );
  }

  // Lavender "related links" band — left heading column, right stacked
  // link rows with arrows + dividers (the recurring "you might also be
  // interested" / "keep exploring" section).
  if (surface === 'related') {
    return (
      <section className={BAND_SHELL}>
        <div className="grid gap-8 rounded-3xl bg-[#eeedff] px-6 py-12 lg:grid-cols-[1fr_1.5fr] lg:gap-12 lg:px-12 lg:py-14">
          <div>
            {eyebrow && (
              <p className="text-sm font-medium text-[#475c61]">{renderRichText(eyebrow)}</p>
            )}
            {heading && (
              <h2
                className="mt-2 text-2xl sm:text-3xl lg:text-4xl"
                style={{ ...DISPLAY_STYLE, color: '#1a353e' }}
              >
                {renderRichText(heading)}
              </h2>
            )}
            {subheading && (
              <RichTextBlock text={subheading} className="mt-3 max-w-md text-[#475c61]" />
            )}
          </div>
          {links && links.length > 0 && (
            <ul className="self-center">
              {links.map((link, idx) => (
                <li
                  key={link.href || link.label || `cta-row-${idx}`}
                  className="border-t border-[#1a353e]/15 last:border-b"
                >
                  <a
                    href={link.href || '#'}
                    className="flex items-center justify-between gap-4 py-4 text-[#1a353e] transition-opacity hover:opacity-70"
                  >
                    <span className="font-medium">
                      {renderRichText(link.label || '', {
                        allowLinks: false,
                      })}
                    </span>
                    <span aria-hidden="true">→</span>
                  </a>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    );
  }

  // Lavender "soft" band — centered heading with a row of text links.
  // Sized to the GCA design system (H2 44 Light, 18px SemiBold links —
  // SNAG_012).
  if (surface === 'soft') {
    return (
      <section className={BAND_SHELL}>
        <div className="rounded-3xl bg-[#eeedff] px-6 py-14 text-center lg:py-20">
          {heading && (
            <h2
              className="mx-auto max-w-4xl leading-[var(--pb-heading-leading,1.15)]"
              style={SOFT_HEADING_STYLE}
            >
              {renderRichText(heading)}
            </h2>
          )}
          {subheading && (
            <RichTextBlock
              text={subheading}
              className="mx-auto mt-4 max-w-2xl text-[17px] text-[#475c61]"
            />
          )}
          {links && links.length > 0 && (
            <div className="mt-8 flex flex-wrap items-center justify-center gap-x-10 gap-y-3">
              {links.map((link, idx) => (
                <a
                  key={link.href || link.label || `cta-pill-${idx}`}
                  href={link.href || '#'}
                  className="text-[17px] font-semibold text-[#1a353e] transition-colors hover:text-[#468f8c]"
                >
                  {renderRichText(link.label || '', { allowLinks: false })}
                </a>
              ))}
            </div>
          )}
        </div>
      </section>
    );
  }

  // Lime "Get involved" band — text + button left, image collage right.
  // The main call to action: display-size heading, 20px body, white pill
  // button that inverts to ink on hover (design-system "Secondary" button —
  // SNAG_013).
  if (surface === 'lime') {
    return (
      <section className={BAND_SHELL}>
        <div className="grid items-center gap-10 rounded-3xl bg-[#d8ec29] px-6 py-12 lg:grid-cols-2 lg:gap-16 lg:px-14 lg:py-16">
          <div>
            {heading && (
              <h2 className="leading-[var(--pb-heading-leading,1.15)]" style={LIME_HEADING_STYLE}>
                {renderRichText(heading)}
              </h2>
            )}
            {subheading && (
              <RichTextBlock
                text={subheading}
                className="mt-6 max-w-md text-[19px] leading-relaxed text-[#1a353e]/85"
              />
            )}
            {primaryLabel && (
              <a
                href={primaryHref || '#'}
                className="mt-8 inline-flex items-center justify-center rounded-full bg-white px-7 py-3 text-[17px] font-semibold text-[#1a353e] transition-colors hover:bg-[#1a353e] hover:text-white"
              >
                {renderRichText(primaryLabel, { allowLinks: false })}
              </a>
            )}
          </div>
          {images && images.length > 0 && (
            <div className="grid grid-cols-3 gap-4">
              {images.map((img, idx) => (
                <div
                  key={img.src || img.alt || `cta-img-${idx}`}
                  className="relative aspect-square overflow-hidden rounded-lg bg-[#1a353e]/10"
                >
                  {img.src && (
                    <img
                      src={img.src}
                      alt={img.alt}
                      loading="lazy"
                      className="size-full object-cover"
                    />
                  )}
                  {img.caption && (
                    <span className="absolute bottom-1.5 right-1.5 rounded bg-[#1a353e]/70 px-2 py-0.5 text-[11px] font-medium text-white">
                      {renderRichText(img.caption)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    );
  }

  // Default accent CTA (unchanged — used by other tenants).
  return (
    <Section variant="accent" spacing="default" align={align}>
      <div className="lg:flex lg:items-center lg:justify-between gap-6">
        <div className="flex-1">
          <Heading as="h2" size="md" tone="inverse" text={heading} />
          {subheading && (
            <RichTextBlock text={subheading} className="mt-2 text-xl text-primary-100" />
          )}
        </div>
        <div className="mt-6 lg:mt-0 flex flex-wrap gap-3">
          <CTAButton label={primaryLabel} href={primaryHref} variant="inverse-primary" />
          <CTAButton label={secondaryLabel} href={secondaryHref} variant="inverse-outline" />
        </div>
      </div>
    </Section>
  );
};
