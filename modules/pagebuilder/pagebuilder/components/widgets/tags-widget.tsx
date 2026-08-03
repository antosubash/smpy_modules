import type { ComponentConfig } from '@measured/puck';
import { cn } from '../../utils/widgetUtils';
import { renderRichText } from './_internal/rich-text';

export type TagItem = {
  label: string;
  href: string;
  active: boolean;
};

export type TagsWidgetProps = {
  label: string;
  items: TagItem[];
};

export const TagsWidget: ComponentConfig<TagsWidgetProps> = {
  label: 'Tags (pill row)',
  fields: {
    label: { type: 'text', label: 'Aria label' },
    items: {
      type: 'array',
      label: 'Tags',
      arrayFields: {
        label: { type: 'text', label: 'Label' },
        href: { type: 'text', label: 'Link' },
        active: {
          type: 'radio',
          label: 'Active',
          options: [
            { label: 'No', value: false },
            { label: 'Yes', value: true },
          ],
        },
      },
      defaultItemProps: { label: 'Tag', href: '#', active: false },
      min: 1,
      max: 50,
    },
  },
  defaultProps: {
    label: 'Filters',
    items: [
      { label: 'All', href: '#', active: true },
      { label: 'English', href: '#', active: false },
      { label: 'Français', href: '#', active: false },
    ],
  },
  render: ({ label, items }) =>
    !items || items.length === 0 ? (
      <div className="text-gray-500 text-center py-4">Add tags in the editor.</div>
    ) : (
      <nav aria-label={label || 'Tags'} className="container mx-auto px-4 py-4 sm:px-6 lg:px-8">
        <ul className="flex flex-wrap gap-2">
          {items.map((tag, idx) => (
            <li key={tag.label || tag.href || `tag-${idx}`}>
              <a
                href={tag.href || '#'}
                aria-current={tag.active ? 'page' : undefined}
                className={cn(
                  'inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors',
                  tag.active
                    ? 'border-primary-700 bg-primary-50 text-primary-800'
                    : 'border-gray-200 text-gray-700 hover:border-primary-300 hover:bg-primary-50',
                )}
              >
                {/* Radio-style indicator (filled when active) — matches the
								    GCA filter pills. */}
                <span
                  aria-hidden="true"
                  className={cn(
                    'flex size-3.5 shrink-0 items-center justify-center rounded-full border',
                    tag.active ? 'border-primary-700' : 'border-gray-300',
                  )}
                >
                  {tag.active && <span className="size-1.5 rounded-full bg-primary-700" />}
                </span>
                {renderRichText(tag.label, { allowLinks: false })}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    ),
};
