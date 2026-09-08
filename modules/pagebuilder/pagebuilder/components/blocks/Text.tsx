import type { ComponentConfig } from '@puckeditor/core';
import { keys } from '../../utils/i18n';
import { cn } from '../../utils/widgetUtils';
import { RichTextBlock } from '../widgets/_internal/rich-text';

interface TextProps {
  /**
   * Light markdown, not HTML: `**bold**`, `*italic*`, `` `code` ``,
   * `[label](href)`, `- ` bullets and blank-line paragraphs. See the note on
   * the field below for why this isn't Puck's `richtext`.
   */
  text: string;
  size: 'sm' | 'base' | 'lg' | 'xl';
  align: 'left' | 'center' | 'right';
}

const sizeClass: Record<TextProps['size'], string> = {
  sm: 'text-sm',
  base: 'text-base',
  lg: 'text-lg',
  xl: 'text-xl',
};

// Spelled out rather than `text-${align}` — Tailwind's scanner cannot see an
// interpolated class name. See the same note in Heading.
const alignClass: Record<TextProps['align'], string> = {
  left: 'text-left',
  center: 'text-center',
  right: 'text-right',
};

export const TextBlock: ComponentConfig<TextProps> = {
  label: keys.pagebuilder.blocks.text.label,
  fields: {
    /**
     * Upstream uses Puck's `richtext` field here, which stores HTML and hands
     * it to Puck to render. This stays a textarea rendered through
     * `RichTextBlock`, which parses light markdown into React elements.
     *
     * Same expressive range for an author — bold, italic, code, links, bullets,
     * paragraphs — but nothing on a published page is ever built from stored
     * markup, so there is no injection surface to sanitise. That matters more
     * here than upstream: pages reach the public viewer through a review
     * workflow, and the CSP that would otherwise be the backstop is an
     * operator-tunable setting that can be emptied. It also keeps this block
     * consistent with the other 50, which all render copy this way.
     */
    text: { type: 'textarea', label: keys.pagebuilder.blocks.text.text },
    size: {
      type: 'select',
      label: keys.pagebuilder.blocks.text.size,
      options: [
        { label: keys.pagebuilder.blocks.text.size_sm, value: 'sm' },
        { label: keys.pagebuilder.blocks.text.size_base, value: 'base' },
        { label: keys.pagebuilder.blocks.text.size_lg, value: 'lg' },
        { label: keys.pagebuilder.blocks.text.size_xl, value: 'xl' },
      ],
    },
    align: {
      type: 'radio',
      label: keys.pagebuilder.blocks.text.align,
      options: [
        { label: keys.pagebuilder.blocks.text.align_left, value: 'left' },
        { label: keys.pagebuilder.blocks.text.align_center, value: 'center' },
        { label: keys.pagebuilder.blocks.text.align_right, value: 'right' },
      ],
    },
  },
  defaultProps: { text: 'Some descriptive text.', size: 'base', align: 'left' },
  // `size` is defaulted here too: every Text already on a page predates the
  // field and arrives undefined, which would index `sizeClass` to `undefined`.
  render: ({ text, size = 'base', align = 'left' }) => (
    <div className="container mx-auto px-4 py-2">
      <RichTextBlock
        text={text}
        className={cn('leading-relaxed', sizeClass[size], alignClass[align])}
      />
    </div>
  ),
};
