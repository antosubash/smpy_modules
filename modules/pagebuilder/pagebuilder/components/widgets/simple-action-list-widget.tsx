import type { ComponentConfig } from '@puckeditor/core';
import { renderRichText } from './_internal/rich-text';

export type SimpleActionItem = {
  title: string;
  description: string;
  href: string;
};

export type SimpleActionListWidgetProps = {
  title: string;
  items: SimpleActionItem[];
};

export const SimpleActionListWidget: ComponentConfig<SimpleActionListWidgetProps> = {
  label: 'Action List',
  fields: {
    title: { type: 'text', label: 'Title' },
    items: {
      type: 'array',
      label: 'Actions',
      arrayFields: {
        title: { type: 'text', label: 'Title' },
        // Each row is a link, so markdown links here render as label text.
        description: {
          type: 'textarea',
          label: 'Description (links not supported here)',
        },
        href: { type: 'text', label: 'Link URL' },
      },
      defaultItemProps: {
        title: 'Action',
        description: 'Description...',
        href: '#',
      },
      min: 1,
      max: 20,
    },
  },
  defaultProps: {
    title: 'Quick links',
    items: [
      {
        title: 'Documentation',
        description: 'Read the docs',
        href: '#',
      },
      {
        title: 'API reference',
        description: 'Browse the API',
        href: '#',
      },
    ],
  },
  render: ({ title, items }) => (
    <div className="container mx-auto px-4 py-12 max-w-3xl">
      {title && <h2 className="text-2xl font-light mb-6">{renderRichText(title)}</h2>}
      <div className="divide-y border rounded-lg overflow-hidden">
        {items?.map((item, idx) => (
          <a
            // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
            key={idx}
            href={item.href || '#'}
            className="flex items-center justify-between p-4 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          >
            <div>
              <div className="font-semibold">
                {renderRichText(item.title, { allowLinks: false })}
              </div>
              {item.description && (
                <div className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                  {renderRichText(item.description, { allowLinks: false })}
                </div>
              )}
            </div>
            <svg
              className="size-5 text-gray-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <title>Arrow</title>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </a>
        ))}
      </div>
    </div>
  ),
};
