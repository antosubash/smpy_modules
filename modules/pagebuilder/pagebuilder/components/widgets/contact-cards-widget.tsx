import type { ComponentConfig } from '@measured/puck';
import { User } from 'lucide-react';
import type { CSSProperties } from 'react';
import { createImageField, mediaLibraryAdapter } from '../../fields';
import { AccentText } from './_internal/accent-text';
import { renderRichText } from './_internal/rich-text';

export type ContactCardItem = {
  name: string;
  role: string;
  email: string;
  phone: string;
  imageUrl: string;
};

export type ContactCardsWidgetProps = {
  eyebrow: string;
  title: string;
  variant: 'contact' | 'team';
  items: ContactCardItem[];
};

const DISPLAY_STYLE: CSSProperties = {
  fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
  letterSpacing: 'var(--pb-display-tracking)',
  fontFamily: 'var(--pb-display-font)',
  color: 'var(--pb-heading-color)',
};

export const ContactCardsWidget: ComponentConfig<ContactCardsWidgetProps> = {
  label: 'Contact Cards',
  fields: {
    eyebrow: { type: 'text', label: 'Eyebrow' },
    title: { type: 'text', label: 'Title' },
    variant: {
      type: 'select',
      label: 'Style',
      options: [
        { label: 'Contact (round avatar)', value: 'contact' },
        { label: 'Team (image-top card)', value: 'team' },
      ],
    },
    items: {
      type: 'array',
      label: 'Contacts',
      arrayFields: {
        name: { type: 'text', label: 'Name' },
        role: { type: 'text', label: 'Role' },
        email: { type: 'text', label: 'Email' },
        phone: { type: 'text', label: 'Phone' },
        imageUrl: createImageField(mediaLibraryAdapter, 'Image'),
      },
      defaultItemProps: {
        name: 'Jane Doe',
        role: 'Director',
        email: 'jane@example.com',
        phone: '',
        imageUrl: '',
      },
      min: 1,
      max: 12,
    },
  },
  defaultProps: {
    eyebrow: '',
    title: 'Get in touch',
    variant: 'contact',
    items: [
      {
        name: 'Jane Doe',
        role: 'Director',
        email: 'jane@example.com',
        phone: '',
        imageUrl: '',
      },
    ],
  },
  render: ({ eyebrow, title, variant = 'contact', items }) => {
    const team = variant === 'team';
    return (
      <div className="container mx-auto py-12 px-4 sm:px-6 lg:px-8">
        {(eyebrow || title) && (
          <div className="mb-8 text-center">
            {eyebrow && (
              <p className="mb-2 text-sm font-medium text-[#686873]">{renderRichText(eyebrow)}</p>
            )}
            {/* AccentText, not bare renderRichText: this is a display heading
						    on `--pb-display-weight`, where a plain <strong>'s relative
						    `bolder` can compute to no visible change. */}
            {title && (
              <h2 className="text-3xl sm:text-4xl" style={DISPLAY_STYLE}>
                <AccentText text={title} />
              </h2>
            )}
          </div>
        )}
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {items?.map((item, idx) =>
            team ? (
              // Image-top team card: rectangular media (dark placeholder with a
              // person glyph when no photo), left-aligned name + affiliation.
              // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; card content repeats, so a content key collides
              <div key={idx}>
                {item.imageUrl ? (
                  <img
                    src={item.imageUrl}
                    alt={item.name}
                    loading="lazy"
                    className="aspect-[4/3] w-full rounded-xl object-cover"
                  />
                ) : (
                  <div className="flex aspect-[4/3] w-full items-center justify-center rounded-xl bg-[#1a353e]">
                    <User className="size-10 text-white/35" aria-hidden="true" />
                  </div>
                )}
                {item.name && (
                  <h3
                    className="mt-4 text-base font-semibold"
                    style={{ color: 'var(--pb-heading-color)' }}
                  >
                    {renderRichText(item.name)}
                  </h3>
                )}
                {item.role && (
                  <p className="mt-1 text-sm text-[#686873]">{renderRichText(item.role)}</p>
                )}
              </div>
            ) : (
              <div
                // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; card content repeats, so a content key collides
                key={idx}
                className="rounded-lg border bg-white dark:bg-gray-900 p-6 text-center shadow-sm"
              >
                {item.imageUrl ? (
                  <img
                    src={item.imageUrl}
                    alt={item.name}
                    className="size-24 rounded-full mx-auto object-cover"
                  />
                ) : (
                  <div className="size-24 rounded-full mx-auto bg-gradient-to-br from-gray-200 to-gray-300" />
                )}
                <h3 className="mt-4 text-lg font-semibold">{renderRichText(item.name || '')}</h3>
                {item.role && (
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    {renderRichText(item.role)}
                  </p>
                )}
                {item.email && (
                  <a
                    href={`mailto:${item.email}`}
                    className="block mt-2 text-primary-700 hover:underline text-sm break-all"
                  >
                    {item.email}
                  </a>
                )}
                {item.phone && (
                  <a
                    href={`tel:${item.phone}`}
                    className="block text-sm text-gray-600 dark:text-gray-300"
                  >
                    {item.phone}
                  </a>
                )}
              </div>
            ),
          )}
        </div>
      </div>
    );
  },
};
