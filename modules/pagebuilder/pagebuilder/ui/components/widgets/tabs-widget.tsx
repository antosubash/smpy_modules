import type { ComponentConfig } from '@puckeditor/core';
import { useId, useState } from 'react';
import { keys, useT } from '../../utils/i18n';
import { RichTextBlock, renderRichText } from './_internal/rich-text';

export type TabItem = {
  label: string;
  content: string;
};

export type TabsWidgetProps = {
  items: TabItem[];
};

function TabsRenderer({ items }: TabsWidgetProps) {
  const { t } = useT();
  const [active, setActive] = useState(0);
  const baseId = useId();
  if (!items || items.length === 0) {
    return (
      <div className="text-gray-500 text-center py-4">{t(keys.pagebuilder.blocks.tabs.empty)}</div>
    );
  }
  const safeIndex = Math.min(active, items.length - 1);
  return (
    <div className="container mx-auto max-w-3xl py-8">
      <div
        className="border-b flex flex-wrap gap-2"
        role="tablist"
        aria-label={t(keys.pagebuilder.blocks.tabs.tablist)}
      >
        {items.map((item, idx) => {
          const isActive = idx === safeIndex;
          const tabId = `${baseId}-tab-${idx}`;
          const panelId = `${baseId}-panel-${idx}`;
          return (
            <button
              // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
              key={idx}
              id={tabId}
              type="button"
              role="tab"
              aria-selected={isActive}
              aria-controls={panelId}
              tabIndex={isActive ? 0 : -1}
              onClick={() => {
                if (idx !== safeIndex) setActive(idx);
              }}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                isActive
                  ? 'border-primary-700 text-primary-700 dark:text-primary-400 dark:border-primary-300'
                  : 'border-transparent text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100'
              }`}
            >
              {item.label ? renderRichText(item.label, { allowLinks: false }) : `Tab ${idx + 1}`}
            </button>
          );
        })}
      </div>
      <div
        id={`${baseId}-panel-${safeIndex}`}
        role="tabpanel"
        aria-labelledby={`${baseId}-tab-${safeIndex}`}
        className="pt-4"
      >
        {items[safeIndex]?.content && (
          <RichTextBlock
            text={items[safeIndex].content}
            className="leading-relaxed whitespace-pre-line"
          />
        )}
      </div>
    </div>
  );
}

export const TabsWidget: ComponentConfig<TabsWidgetProps> = {
  label: keys.pagebuilder.blocks.tabs.label,
  fields: {
    items: {
      type: 'array',
      label: keys.pagebuilder.blocks.tabs.items,
      arrayFields: {
        label: { type: 'text', label: keys.pagebuilder.blocks.tabs.items_label },
        content: { type: 'textarea', label: keys.pagebuilder.blocks.tabs.items_content },
      },
      defaultItemProps: { label: 'Tab', content: 'Tab content...' },
      min: 1,
      max: 12,
    },
  },
  defaultProps: {
    items: [
      { label: 'Overview', content: 'Overview content...' },
      { label: 'Details', content: 'Details content...' },
    ],
  },
  render: ({ items }) => <TabsRenderer items={items || []} />,
};
