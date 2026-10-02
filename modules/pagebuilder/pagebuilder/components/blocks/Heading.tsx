import type { ComponentConfig } from '@puckeditor/core';
import type { CSSProperties } from 'react';
import { keys } from '../../utils/i18n';
import { cn } from '../../utils/widgetUtils';
import { renderRichText } from '../widgets/_internal/rich-text';

interface HeadingProps {
  text: string;
  /**
   * Stored as `h1`…`h6` rather than upstream's `1`…`6`. The enum is an
   * internal representation, not something an author ever sees, and every
   * Heading already on a page uses this spelling — adopting the other one
   * would mean migrating all of them to change nothing visible.
   */
  level: 'h1' | 'h2' | 'h3' | 'h4' | 'h5' | 'h6';
  align: 'left' | 'center' | 'right';
}

// A lookup map rather than `text-${align}`: Tailwind's scanner only emits
// classes it can see spelled out, and an interpolated name is invisible to it.
// The old form worked by accident — these three names happen to appear
// literally in other files, and would have silently stopped working the day
// they didn't.
const alignClass: Record<HeadingProps['align'], string> = {
  left: 'text-left',
  center: 'text-center',
  right: 'text-right',
};

// Sizes only. Weight, tracking and face for display headings come from the
// design-pack tokens, so one block renders in each pack's style — the previous
// hardcoded `font-bold` overrode the pack.
const sizeClass: Record<HeadingProps['level'], string> = {
  h1: 'text-4xl sm:text-5xl lg:text-6xl leading-[1.1]',
  h2: 'text-3xl sm:text-4xl lg:text-5xl leading-[1.1]',
  h3: 'text-2xl sm:text-3xl',
  h4: 'text-xl sm:text-2xl font-medium',
  h5: 'text-lg sm:text-xl font-medium',
  h6: 'text-base sm:text-lg font-medium',
};

/** h1–h3 are display headings and take the pack's display face and weight. */
const DISPLAY_LEVELS = new Set<HeadingProps['level']>(['h1', 'h2', 'h3']);

function headingStyle(level: HeadingProps['level']): CSSProperties {
  const style: CSSProperties = { color: 'var(--pb-heading-color)' };
  if (DISPLAY_LEVELS.has(level)) {
    style.fontWeight = 'var(--pb-display-weight)' as CSSProperties['fontWeight'];
    style.letterSpacing = 'var(--pb-display-tracking)';
    style.fontFamily = 'var(--pb-display-font)';
  }
  return style;
}

export const HeadingBlock: ComponentConfig<HeadingProps> = {
  label: keys.pagebuilder.blocks.heading.label,
  fields: {
    text: { type: 'text', label: keys.pagebuilder.blocks.heading.text },
    level: {
      type: 'select',
      label: keys.pagebuilder.blocks.heading.level,
      options: [
        { label: keys.pagebuilder.blocks.heading.level_h1, value: 'h1' },
        { label: keys.pagebuilder.blocks.heading.level_h2, value: 'h2' },
        { label: keys.pagebuilder.blocks.heading.level_h3, value: 'h3' },
        { label: keys.pagebuilder.blocks.heading.level_h4, value: 'h4' },
        { label: keys.pagebuilder.blocks.heading.level_h5, value: 'h5' },
        { label: keys.pagebuilder.blocks.heading.level_h6, value: 'h6' },
      ],
    },
    align: {
      type: 'radio',
      label: keys.pagebuilder.blocks.heading.align,
      options: [
        { label: keys.pagebuilder.blocks.heading.align_left, value: 'left' },
        { label: keys.pagebuilder.blocks.heading.align_center, value: 'center' },
        { label: keys.pagebuilder.blocks.heading.align_right, value: 'right' },
      ],
    },
  },
  defaultProps: { text: 'Heading', level: 'h2', align: 'left' },
  render: ({ text, level = 'h2', align = 'left' }) => {
    const Tag = level;
    return (
      <div className="container mx-auto px-4 py-2">
        <Tag className={cn(sizeClass[level], alignClass[align])} style={headingStyle(level)}>
          {renderRichText(text)}
        </Tag>
      </div>
    );
  },
};
