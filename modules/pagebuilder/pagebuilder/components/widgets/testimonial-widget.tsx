import type { ComponentConfig } from '@puckeditor/core';
import { createImageField, mediaLibraryAdapter } from '../../fields';
import { renderRichText } from './_internal/rich-text';

export type TestimonialItem = {
  quote: string;
  name: string;
  role: string;
  avatarUrl: string;
};

export type TestimonialWidgetProps = {
  title: string;
  items: TestimonialItem[];
};

export const TestimonialWidget: ComponentConfig<TestimonialWidgetProps> = {
  label: 'Testimonials',
  fields: {
    title: { type: 'text', label: 'Title' },
    items: {
      type: 'array',
      label: 'Testimonials',
      arrayFields: {
        quote: { type: 'textarea', label: 'Quote' },
        name: { type: 'text', label: 'Name' },
        role: { type: 'text', label: 'Role' },
        avatarUrl: createImageField(mediaLibraryAdapter, 'Avatar URL'),
      },
      defaultItemProps: {
        quote: 'Great product!',
        name: 'Jane Doe',
        role: 'CEO at Acme',
        avatarUrl: '',
      },
      min: 1,
      max: 12,
    },
  },
  defaultProps: {
    title: 'What our customers say',
    items: [
      {
        quote: 'This changed how we work.',
        name: 'Jane Doe',
        role: 'CEO at Acme',
        avatarUrl: '',
      },
      {
        quote: 'Highly recommended.',
        name: 'John Smith',
        role: 'Founder at Beta',
        avatarUrl: '',
      },
    ],
  },
  render: ({ title, items }) => (
    <div className="container mx-auto px-4 py-16">
      {title && (
        <h2 className="text-3xl sm:text-4xl lg:text-5xl font-light text-center mb-12">
          {renderRichText(title)}
        </h2>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        {items?.map((item, idx) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
          <figure key={idx} className="rounded-2xl border bg-white dark:bg-gray-900 p-8 shadow-sm">
            <svg
              className="size-8 text-primary-400"
              fill="currentColor"
              viewBox="0 0 32 32"
              aria-hidden="true"
            >
              <title>Quote</title>
              <path d="M9.352 4C4.456 7.456 1 13.12 1 19.36c0 5.088 3.072 8.064 6.624 8.064 3.36 0 5.856-2.688 5.856-5.856 0-3.168-2.208-5.472-5.088-5.472-.576 0-1.344.096-1.536.192.48-3.264 3.552-7.104 6.624-9.024L9.352 4zm16.512 0c-4.8 3.456-8.256 9.12-8.256 15.36 0 5.088 3.072 8.064 6.624 8.064 3.264 0 5.856-2.688 5.856-5.856 0-3.168-2.304-5.472-5.184-5.472-.576 0-1.248.096-1.44.192.48-3.264 3.456-7.104 6.528-9.024L25.864 4z" />
            </svg>
            <blockquote className="mt-4 text-lg leading-relaxed">
              {renderRichText(item.quote)}
            </blockquote>
            <figcaption className="mt-6 flex items-center gap-4">
              {item.avatarUrl ? (
                <img
                  src={item.avatarUrl}
                  alt={item.name}
                  className="size-12 rounded-full object-cover"
                />
              ) : (
                <div className="size-12 rounded-full bg-gradient-to-br from-gray-200 to-gray-300" />
              )}
              <div>
                <div className="font-semibold">{renderRichText(item.name)}</div>
                <div className="text-sm text-gray-500 dark:text-gray-400">
                  {renderRichText(item.role)}
                </div>
              </div>
            </figcaption>
          </figure>
        ))}
      </div>
    </div>
  ),
};
