import type { ComponentConfig } from '@puckeditor/core';
import { renderRichText } from './_internal/rich-text';

export type ListWidgetProps = {
  type: 'ul' | 'ol';
  items: string;
};

export const ListWidget: ComponentConfig<ListWidgetProps> = {
  label: 'List',
  fields: {
    type: {
      type: 'select',
      label: 'List type',
      options: [
        { label: 'Unordered', value: 'ul' },
        { label: 'Ordered', value: 'ol' },
      ],
    },
    items: {
      type: 'textarea',
      label: 'Items (one per line)',
    },
  },
  defaultProps: {
    type: 'ul',
    items: 'First item\nSecond item\nThird item',
  },
  render: ({ type, items }) => {
    const list = items
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    const className =
      type === 'ol' ? 'list-decimal list-inside space-y-1' : 'list-disc list-inside space-y-1';
    return (
      <div className="container mx-auto px-4 py-2">
        {type === 'ol' ? (
          <ol className={`${className} max-w-3xl mx-auto`}>
            {list.map((item, idx) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
              <li key={idx}>{renderRichText(item)}</li>
            ))}
          </ol>
        ) : (
          <ul className={`${className} max-w-3xl mx-auto`}>
            {list.map((item, idx) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
              <li key={idx}>{renderRichText(item)}</li>
            ))}
          </ul>
        )}
      </div>
    );
  },
};
