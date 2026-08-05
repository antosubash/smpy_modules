import type { ComponentConfig } from '@puckeditor/core';
import { cn } from '../../utils/widgetUtils';
import { renderRichText } from './_internal/rich-text';

export type QuoteWidgetProps = {
  quote: string;
  author: string;
  source: string;
  align: 'left' | 'center';
};

export const QuoteWidget: ComponentConfig<QuoteWidgetProps> = {
  label: 'Quote',
  fields: {
    quote: { type: 'textarea', label: 'Quote' },
    author: { type: 'text', label: 'Author' },
    source: { type: 'text', label: 'Source' },
    align: {
      type: 'select',
      label: 'Alignment',
      options: [
        { label: 'Left', value: 'left' },
        { label: 'Center', value: 'center' },
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
