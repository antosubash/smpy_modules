import type { ComponentConfig } from '@puckeditor/core';
import { keys, translate } from '../../utils/i18n';
import { DisclosureChevron } from './_internal/disclosure-chevron';
import { RichTextBlock, renderRichText } from './_internal/rich-text';

export type AccordionItem = {
  title: string;
  content: string;
};

export type AccordionWidgetProps = {
  items: AccordionItem[];
};

export const AccordionWidget: ComponentConfig<AccordionWidgetProps> = {
  label: keys.pagebuilder.blocks.accordion.label,
  fields: {
    items: {
      type: 'array',
      label: keys.pagebuilder.blocks.accordion.items,
      arrayFields: {
        title: { type: 'text', label: keys.pagebuilder.blocks.accordion.items_title },
        content: { type: 'textarea', label: keys.pagebuilder.blocks.accordion.items_content },
      },
      defaultItemProps: {
        title: 'Section title',
        content: 'Section content...',
      },
      min: 1,
      max: 20,
    },
  },
  defaultProps: {
    items: [
      { title: 'Section 1', content: 'Content for section 1...' },
      { title: 'Section 2', content: 'Content for section 2...' },
    ],
  },
  render: ({ items }) => {
    if (!items || items.length === 0) {
      return (
        <div className="text-gray-500 text-center py-4">
          {translate(keys.pagebuilder.blocks.accordion.empty)}
        </div>
      );
    }
    return (
      <div className="container mx-auto max-w-3xl py-8 space-y-2">
        {items.map((item, idx) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
          <details key={idx} className="group rounded-lg border bg-white dark:bg-gray-900 p-4">
            <summary className="cursor-pointer flex items-center justify-between font-semibold list-none">
              {renderRichText(item.title || `Item ${idx + 1}`, {
                allowLinks: false,
              })}
              <DisclosureChevron />
            </summary>
            <RichTextBlock
              text={item.content}
              className="mt-3 text-gray-700 dark:text-gray-300 leading-relaxed"
            />
          </details>
        ))}
      </div>
    );
  },
};
