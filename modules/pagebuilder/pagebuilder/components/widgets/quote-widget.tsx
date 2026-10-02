import type { ComponentConfig } from '@puckeditor/core';
import { keys } from '../../utils/i18n';
import { cn } from '../../utils/widgetUtils';
import { renderRichText } from './_internal/rich-text';

export type QuoteWidgetProps = {
  quote: string;
  author: string;
  source: string;
  align: 'left' | 'center';
};

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
        'max-w-3xl mx-auto px-4 py-10 border-l-4 border-primary-700 bg-primary-50/50 dark:bg-primary-950/30 rounded-r-lg',
        align === 'center' ? 'text-center' : 'text-left',
      )}
    >
      <blockquote className="text-xl sm:text-2xl italic text-gray-800 dark:text-gray-100 leading-relaxed">
        “{renderRichText(quote)}”
      </blockquote>
      {(author || source) && (
        <figcaption className="mt-4 text-gray-600 dark:text-gray-400">
          {author && <span className="font-semibold">— {renderRichText(author)}</span>}
          {source && <span className="ml-2 text-sm">({renderRichText(source)})</span>}
        </figcaption>
      )}
    </figure>
  ),
};
