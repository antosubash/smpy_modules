import type { ComponentConfig } from '@puckeditor/core';
import type { CSSProperties } from 'react';
import { keys } from '../../utils/i18n';
import { cn } from '../../utils/widgetUtils';
import { RichTextBlock, renderRichText } from './_internal/rich-text';
import { eyebrowTextStyle } from './_shared';

export type SectionIntroWidgetProps = {
  eyebrow: string;
  heading: string;
  body: string;
  align: 'left' | 'center';
  layout: 'stacked' | 'split';
  ctaLabel: string;
  ctaHref: string;
};

const headingStyle: CSSProperties = {
  fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
  letterSpacing: 'var(--pb-display-tracking)',
  fontFamily: 'var(--pb-display-font)',
  fontSize: 'var(--pb-heading-lg, clamp(1.875rem, 1.3rem + 2.5vw, 3rem))',
  color: 'var(--pb-heading-color)',
};

export const SectionIntroWidget: ComponentConfig<SectionIntroWidgetProps> = {
  label: keys.pagebuilder.blocks.section_intro.label,
  fields: {
    eyebrow: { type: 'text', label: keys.pagebuilder.blocks.section_intro.eyebrow },
    heading: { type: 'text', label: keys.pagebuilder.blocks.common.heading },
    body: { type: 'textarea', label: keys.pagebuilder.blocks.section_intro.body },
    align: {
      type: 'select',
      label: keys.pagebuilder.blocks.common.align,
      options: [
        { label: keys.pagebuilder.blocks.common.align_left, value: 'left' },
        { label: keys.pagebuilder.blocks.common.align_center, value: 'center' },
      ],
    },
    layout: {
      type: 'select',
      label: keys.pagebuilder.blocks.section_intro.layout,
      options: [
        { label: keys.pagebuilder.blocks.section_intro.layout_stacked, value: 'stacked' },
        { label: keys.pagebuilder.blocks.section_intro.layout_split, value: 'split' },
      ],
    },
    ctaLabel: { type: 'text', label: keys.pagebuilder.blocks.section_intro.cta_label },
    ctaHref: { type: 'text', label: keys.pagebuilder.blocks.section_intro.cta_href },
  },
  defaultProps: {
    eyebrow: '',
    heading: 'Our mission',
    body: 'We help people build great things.',
    align: 'left',
    layout: 'stacked',
    ctaLabel: '',
    ctaHref: '',
  },
  render: ({ eyebrow, heading, body, align, layout, ctaLabel, ctaHref }) => {
    const content = (
      <div
        className={cn(
          'flex flex-col gap-6',
          align === 'center' ? 'items-center text-center' : 'items-start',
        )}
      >
        {heading && (
          <h2 className="leading-[var(--pb-heading-leading,1.1)]" style={headingStyle}>
            {renderRichText(heading)}
          </h2>
        )}
        {body && (
          <RichTextBlock
            text={body}
            className={cn(
              'text-lg leading-[var(--pb-body-leading,1.625)]',
              // Mowing Figma: the split intro's body wraps at 432px.
              layout === 'split' && 'max-w-[432px]',
            )}
            style={{ color: 'var(--pb-body-color)' }}
          />
        )}
        {ctaLabel && (
          <a
            href={ctaHref || '#'}
            className="inline-flex items-center rounded-full bg-[var(--primary,#000000)] px-7 py-4 font-medium text-[var(--primary-foreground,#ffffff)] transition-opacity hover:opacity-90"
          >
            {renderRichText(ctaLabel, { allowLinks: false })}
          </a>
        )}
      </div>
    );

    // Split column geometry is tenant-tunable via `--pb-split-cols`/
    // `--pb-split-gap` (Mowing aligns the content to the 4th page-grid
    // column); the 1fr/2fr fallback keeps tenants without the tokens on the
    // prior layout.
    if (layout === 'split') {
      return (
        <section className="container mx-auto px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8">
          <div className="grid gap-6 md:grid-cols-[var(--pb-split-cols,1fr_2fr)] md:gap-x-[var(--pb-split-gap,1.5rem)]">
            {eyebrow && (
              <p
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
            <div className={eyebrow ? undefined : 'md:col-span-2'}>{content}</div>
          </div>
        </section>
      );
    }

    return (
      <section
        className={cn(
          'container mx-auto px-4 py-[var(--pb-section-py,3rem)] max-w-4xl flex flex-col gap-4',
          align === 'center' ? 'text-center' : 'text-left',
        )}
      >
        {eyebrow && (
          <p
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
        {content}
      </section>
    );
  },
};
