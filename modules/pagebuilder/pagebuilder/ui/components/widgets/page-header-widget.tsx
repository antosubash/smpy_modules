import type { ComponentConfig } from '@puckeditor/core';
import { keys } from '../../utils/i18n';
import { cn } from '../../utils/widgetUtils';
import { RichTextBlock } from './_internal/rich-text';
import { CTAButton, EyebrowText, Heading, Section } from './_shared';

export type PageHeaderWidgetProps = {
  eyebrow: string;
  title: string;
  description: string;
  align: 'left' | 'center';
  ctaLabel: string;
  ctaHref: string;
  /**
   * Left-aligned headers can start at a page-grid column instead of the
   * container edge (Mowing Figma: the landing hero sits at the 2nd column,
   * the campaign/contact headers at the 4th). "none" keeps the legacy
   * edge-aligned layout.
   */
  indent?: 'none' | '2' | '4';
  /** Description text width: "auto" keeps the legacy max-w-3xl. */
  bodyWidth?: 'auto' | '546';
};

// 12-col grid placement (gap 24px) matching the Figma page grid.
const INDENT_CLASSES: Record<'2' | '4', string> = {
  '2': 'lg:col-start-2 lg:col-span-10',
  '4': 'lg:col-start-4 lg:col-span-9',
};

export const PageHeaderWidget: ComponentConfig<PageHeaderWidgetProps> = {
  label: keys.pagebuilder.blocks.page_header.label,
  fields: {
    eyebrow: { type: 'text', label: keys.pagebuilder.blocks.page_header.eyebrow },
    title: { type: 'text', label: keys.pagebuilder.blocks.common.title },
    description: { type: 'textarea', label: keys.pagebuilder.blocks.common.description },
    align: {
      type: 'select',
      label: keys.pagebuilder.blocks.common.align,
      options: [
        { label: keys.pagebuilder.blocks.common.align_center, value: 'center' },
        { label: keys.pagebuilder.blocks.common.align_left, value: 'left' },
      ],
    },
    indent: {
      type: 'select',
      label: keys.pagebuilder.blocks.page_header.indent,
      options: [
        { label: keys.pagebuilder.blocks.page_header.indent_none, value: 'none' },
        { label: keys.pagebuilder.blocks.page_header.indent_2, value: '2' },
        { label: keys.pagebuilder.blocks.page_header.indent_4, value: '4' },
      ],
    },
    bodyWidth: {
      type: 'select',
      label: keys.pagebuilder.blocks.page_header.body_width,
      options: [
        { label: keys.pagebuilder.blocks.page_header.body_width_auto, value: 'auto' },
        { label: keys.pagebuilder.blocks.page_header.body_width_546, value: '546' },
      ],
    },
    ctaLabel: { type: 'text', label: keys.pagebuilder.blocks.page_header.cta_label },
    ctaHref: { type: 'text', label: keys.pagebuilder.blocks.page_header.cta_href },
  },
  defaultProps: {
    eyebrow: 'Section',
    title: '',
    description: 'Supporting description that introduces the page.',
    align: 'center',
    indent: 'none',
    bodyWidth: 'auto',
    ctaLabel: '',
    ctaHref: '',
  },
  render: ({
    eyebrow,
    title,
    description,
    align = 'center',
    indent = 'none',
    bodyWidth = 'auto',
    ctaLabel,
    ctaHref,
  }) => {
    const left = align === 'left';
    const gridIndent = left && indent !== 'none' ? INDENT_CLASSES[indent] : '';
    const inner = (
      <div
        className={cn(
          'flex flex-col gap-[var(--pb-hero-gap,1rem)]',
          left ? 'items-start text-left' : 'items-center',
          gridIndent,
        )}
      >
        <EyebrowText tone="primary">{eyebrow}</EyebrowText>
        <div className={cn('w-full', left ? 'max-w-4xl' : '')}>
          <Heading as="h1" size="lg" text={title} align={left ? 'left' : 'center'} accent />
        </div>
        {description && (
          <RichTextBlock
            text={description}
            className={cn(
              'text-lg',
              bodyWidth === '546' ? 'max-w-[546px]' : 'max-w-3xl',
              !left && 'mx-auto',
            )}
            style={{ color: 'var(--pb-body-color)' }}
          />
        )}
        <CTAButton label={ctaLabel} href={ctaHref} variant="primary" />
      </div>
    );
    return (
      <Section as="header" variant="default" spacing="default" align={left ? 'left' : 'center'}>
        {gridIndent ? <div className="lg:grid lg:grid-cols-12 lg:gap-6">{inner}</div> : inner}
      </Section>
    );
  },
};
