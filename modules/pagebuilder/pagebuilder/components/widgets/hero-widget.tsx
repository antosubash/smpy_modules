import type { ComponentConfig } from '@puckeditor/core';
import { createCheckboxField, createImageField, mediaLibraryAdapter } from '../../fields';
import { cn } from '../../utils/widgetUtils';
import { RichTextBlock } from './_internal/rich-text';
import {
  BackgroundMedia,
  ContentMedia,
  CTAButton,
  EyebrowText,
  Heading,
  imageSrcsetField,
  maskStyle,
  resolveImageSrcset,
  Section,
  SIZES_HALF,
  srcsetAttrs,
} from './_shared';

import type { HeroWidgetProps } from './hero-widget-props';

export type { HeroWidgetProps } from './hero-widget-props';

// Exported so CenteredHeroWidget can render through it without smuggling
// Puck's ComponentConfig.render signature past the type system.
export function renderHero({
  eyebrow,
  title,
  subtitle,
  logoUrl,
  logoAlt,
  imageUrl,
  imageAlt,
  imageSrcset = '',
  imageMaskUrl = '',
  imageShape = 'rounded',
  imagePosition,
  primaryLabel,
  primaryHref,
  secondaryLabel,
  secondaryHref,
  overlay,
  align,
  surface,
}: HeroWidgetProps) {
  // A brand-logo lockup (e.g. a script wordmark) can stand in for the plain
  // text title; the title then only feeds screen readers.
  // Both axes are capped so a tenant can pin the lockup to its Figma box
  // (BioGarden: 371x268 on the background hero, 445x214 on the side-image
  // one). `--pb-hero-logo-max-w` defaults to 100%, i.e. the previous
  // `max-w-full`; the side layout's tokens fall back to the background ones.
  const logoImg = (side: boolean) =>
    logoUrl ? (
      <h1 className={align === 'center' ? 'flex justify-center' : 'flex'}>
        <img
          src={logoUrl}
          alt={logoAlt || title}
          className={
            side
              ? 'max-h-[var(--pb-hero-side-logo-max-h,var(--pb-hero-logo-max-h,14rem))] w-auto max-w-[var(--pb-hero-side-logo-max-w,var(--pb-hero-logo-max-w,100%))] object-contain'
              : 'max-h-[var(--pb-hero-logo-max-h,14rem)] w-auto max-w-[var(--pb-hero-logo-max-w,100%)] object-contain'
          }
        />
      </h1>
    ) : null;
  const heading = logoImg(false);

  if (imagePosition === 'background') {
    const content = (
      <>
        <EyebrowText tone="inverse">{eyebrow}</EyebrowText>
        {heading ?? <Heading as="h1" size="xl" tone="inverse" text={title} align={align} accent />}
        {/* Size/weight/opacity are themeable: BioGarden's Figma sets the hero
				    lede in Body 20M (Medium, full white); the fallbacks keep the
				    previous regular-weight 90%-white 20px for other tenants. */}
        {subtitle && (
          <RichTextBlock
            text={subtitle}
            className="mt-6 text-[length:var(--pb-hero-subtitle-size,1.25rem)] font-[number:var(--pb-hero-subtitle-weight,400)] leading-relaxed text-white opacity-[var(--pb-hero-subtitle-opacity,0.9)]"
          />
        )}
        <div
          className={cn(
            'flex flex-wrap gap-4 mt-8',
            align === 'center' ? 'justify-center' : 'justify-start',
          )}
        >
          <CTAButton label={primaryLabel} href={primaryHref} variant="inverse-primary" />
          <CTAButton label={secondaryLabel} href={secondaryHref} variant="inverse-outline" />
        </div>
      </>
    );
    return (
      <section
        className="relative isolate flex min-h-[var(--pb-hero-min-h,560px)] items-center overflow-hidden bg-slate-900 text-white"
        // `--pb-hero-pull` (default 0) lets a full-bleed hero slide up under
        // a normal-flow floating header (the pill nav) so the photo shows
        // through behind it, as in the BioGarden Figma.
        style={{ marginTop: 'var(--pb-hero-pull, 0px)' }}
      >
        <BackgroundMedia
          imageUrl={imageUrl}
          imageAlt={imageAlt}
          imageSrcset={imageSrcset}
          overlay={overlay ? 'dark' : 'none'}
          fallback="gradient-mesh"
          objectPosition="var(--pb-hero-image-position, 50% 50%)"
        />
        <div className="container mx-auto px-4 py-20 sm:px-6 lg:px-8 lg:py-28">
          <div
            className={cn(
              'relative max-w-3xl text-white',
              align === 'center' ? 'mx-auto text-center' : '',
            )}
          >
            {surface === 'card' ? (
              <div className="bg-black/60 p-8 sm:p-12 rounded-lg">{content}</div>
            ) : (
              content
            )}
          </div>
        </div>
      </section>
    );
  }

  return (
    // The side-image hero's top/bottom rhythm is its own: the Figma sets the
    // artwork 152px below the page top (i.e. 52px under the 100px-tall header)
    // and 100px above the next section, which the symmetric section padding
    // can't express. Section emits BOTH `py-*` and `lg:py-*`, and the `lg:`
    // rule is emitted after the unprefixed one, so an unprefixed `pt-*` alone
    // silently loses at desktop — the override has to be stated for both
    // breakpoints. Unset, every token resolves to Section's own padding, so
    // tenants without them are untouched.
    <Section
      variant="default"
      spacing="loose"
      className="pt-[var(--pb-hero-side-pt,var(--pb-section-py,4rem))] pb-[var(--pb-hero-side-pb,var(--pb-section-py,4rem))] lg:pt-[var(--pb-hero-side-pt,var(--pb-section-py,6rem))] lg:pb-[var(--pb-hero-side-pb,var(--pb-section-py,6rem))]"
    >
      <div
        className={cn(
          'flex flex-col lg:flex-row items-center gap-12',
          imagePosition === 'left' ? 'lg:flex-row-reverse' : '',
        )}
      >
        <div className="flex-1">
          <EyebrowText>{eyebrow}</EyebrowText>
          {logoImg(true) ?? <Heading as="h1" size="xl" text={title} accent />}
          {subtitle && (
            <RichTextBlock
              text={subtitle}
              className="mt-6 text-xl leading-relaxed"
              style={{ color: 'var(--pb-body-color)' }}
            />
          )}
          {/* Both CTAButtons render null when their label is blank, but the
					    row itself still contributed its `mt-8`, pushing the column's
					    content up by half that — enough to visibly break the Figma's
					    "logo vertically centred on the image" in the side layout. */}
          {(primaryLabel || secondaryLabel) && (
            <div className="flex flex-wrap gap-4 mt-8">
              <CTAButton label={primaryLabel} href={primaryHref} variant="primary" />
              <CTAButton label={secondaryLabel} href={secondaryHref} variant="secondary" />
            </div>
          )}
        </div>
        <div className="flex-1">
          {imageShape === 'native' && imageUrl ? (
            // Supplied cut-out: rendered exactly as delivered, capped to the
            // Figma's box width. No mask, no crop — the file IS the shape.
            <img
              src={imageUrl}
              {...srcsetAttrs(imageSrcset, SIZES_HALF)}
              alt={imageAlt || title}
              loading="lazy"
              className="h-auto w-full max-w-[var(--pb-hero-media-max-w,none)]"
            />
          ) : imageMaskUrl && imageUrl ? (
            // `--pb-hero-media-max-w` / `--pb-hero-media-aspect` pin the
            // organic cut-out to the Figma's box (BioGarden: 545x481);
            // unset, the image keeps its previous free-flowing size.
            <img
              src={imageUrl}
              {...srcsetAttrs(imageSrcset, SIZES_HALF)}
              alt={imageAlt || title}
              loading="lazy"
              className="h-auto w-full max-w-[var(--pb-hero-media-max-w,none)] object-cover"
              style={{
                ...maskStyle(imageMaskUrl),
                aspectRatio: 'var(--pb-hero-media-aspect, auto)',
              }}
            />
          ) : (
            <ContentMedia
              imageUrl={imageUrl}
              imageAlt={imageAlt}
              imageSrcset={imageSrcset}
              sizes={SIZES_HALF}
              aspect="square"
            />
          )}
        </div>
      </div>
    </Section>
  );
}

export const HeroWidget: ComponentConfig<HeroWidgetProps> = {
  label: 'Hero',
  fields: {
    eyebrow: { type: 'text', label: 'Eyebrow (optional)' },
    title: { type: 'text', label: 'Title' },
    subtitle: { type: 'textarea', label: 'Subtitle' },
    logoUrl: createImageField(mediaLibraryAdapter, 'Logo image (replaces title, optional)'),
    logoAlt: { type: 'text', label: 'Logo alt text' },
    imageUrl: createImageField(mediaLibraryAdapter, 'Image'),
    imageAlt: { type: 'text', label: 'Image alt text' },
    imageSrcset: imageSrcsetField,
    imageMaskUrl: {
      type: 'text',
      label: 'Image mask URL (organic shape, side layouts — optional)',
    },
    imageShape: {
      type: 'select',
      label: 'Image shape (side layouts)',
      options: [
        { label: 'Rounded', value: 'rounded' },
        { label: "Image's own shape (transparent artwork)", value: 'native' },
      ],
    },
    imagePosition: {
      type: 'select',
      label: 'Image position',
      options: [
        { label: 'Background', value: 'background' },
        { label: 'Right', value: 'right' },
        { label: 'Left', value: 'left' },
      ],
    },
    primaryLabel: { type: 'text', label: 'Primary button text' },
    primaryHref: { type: 'text', label: 'Primary button link' },
    secondaryLabel: { type: 'text', label: 'Secondary button text' },
    secondaryHref: { type: 'text', label: 'Secondary button link' },
    overlay: createCheckboxField('Dark overlay (background only)'),
    align: {
      type: 'select',
      label: 'Alignment',
      options: [
        { label: 'Left', value: 'left' },
        { label: 'Center', value: 'center' },
      ],
    },
    surface: {
      type: 'select',
      label: 'Surface (background variant)',
      options: [
        { label: 'Plain', value: 'plain' },
        { label: 'Card overlay', value: 'card' },
      ],
    },
  },
  defaultProps: {
    eyebrow: '',
    title: 'Open knowledge, *mapped*.',
    subtitle: "Discover and contribute to the world's largest community-maintained gazetteer.",
    logoUrl: '',
    logoAlt: '',
    imageUrl: '',
    imageAlt: '',
    imageSrcset: '',
    imageMaskUrl: '',
    imageShape: 'rounded',
    imagePosition: 'background',
    primaryLabel: 'Get started',
    primaryHref: '#',
    secondaryLabel: 'Learn more',
    secondaryHref: '#',
    overlay: true,
    align: 'center',
    surface: 'plain',
  },
  resolveData: resolveImageSrcset,
  render: renderHero,
};
