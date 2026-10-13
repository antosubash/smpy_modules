import type { ComponentConfig } from '@puckeditor/core';
import type { CSSProperties } from 'react';
import { keys } from '../../utils/i18n';
import { cn } from '../../utils/widgetUtils';
import { renderRichText } from './_internal/rich-text';

export type QuoteWidgetProps = {
  quote: string;
  author: string;
  source: string;
  align: 'left' | 'center';
};

// Colours come from the renderer's `--pb-*` tokens rather than a fixed palette,
// so the quote follows the page's theme whether or not it toggles `.dark` —
// a dark branded page would otherwise get dark-grey text on its own navy.
// The tint is mixed from the accent, so it reads on either background.
const FIGURE_STYLE: CSSProperties = {
  borderColor: 'var(--pb-accent)',
  backgroundColor: 'color-mix(in srgb, var(--pb-accent) 8%, transparent)',
};
const CAPTION_STYLE: CSSProperties = { color: 'var(--pb-caption-color, var(--pb-body-color))' };

export const QuoteWidget: ComponentConfig<QuoteWidgetProps> = {
  label: keys.pagebuilder.blocks.quote.label,
  fields: {
    quote: { type: 'textarea', label: keys.pagebuilder.blocks.quote.quote },
    author: { type: 'text', label: keys.pagebuilder.blocks.quote.author },
    source: { type: 'text', label: keys.pagebuilder.blocks.quote.source },
    align: {
      type: 'select',
      label: keys.pagebuilder.blocks.common.align,
      options: [
        { label: keys.pagebuilder.blocks.common.align_left, value: 'left' },
        { label: keys.pagebuilder.blocks.common.align_center, value: 'center' },
      ],
    },
  },
  defaultProps: {
    quote: 'The best way to predict the future is to invent it.',
    author: 'Alan Kay',
    source: '',
    align: 'center',
  },
  render: ({ quote, author, source, align }) => (
    <figure
      className={cn(
        'max-w-3xl mx-auto px-4 py-10 border-l-4 rounded-r-lg',
        align === 'center' ? 'text-center' : 'text-left',
      )}
      style={FIGURE_STYLE}
    >
      <blockquote
        className="text-xl sm:text-2xl italic leading-relaxed"
        style={{ color: 'var(--pb-heading-color)' }}
      >
        “{renderRichText(quote)}”
      </blockquote>
      {(author || source) && (
        <figcaption className="mt-4" style={CAPTION_STYLE}>
          {author && <span className="font-semibold">— {renderRichText(author)}</span>}
          {source && <span className="ml-2 text-sm">({renderRichText(source)})</span>}
        </figcaption>
      )}
    </figure>
  ),
};
