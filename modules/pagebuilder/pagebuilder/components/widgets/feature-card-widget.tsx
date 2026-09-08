import type { ComponentConfig } from '@puckeditor/core';
import type { CSSProperties } from 'react';
import { createImageField, mediaLibraryAdapter } from '../../fields';
import { keys } from '../../utils/i18n';
import { AccentText } from './_internal/accent-text';
import { RichTextBlock, renderRichText } from './_internal/rich-text';

export type FeatureCardWidgetProps = {
  eyebrow: string;
  title: string;
  description: string;
  imageUrl: string;
  imageAlt: string;
  linkLabel: string;
  linkHref: string;
};

export const FeatureCardWidget: ComponentConfig<FeatureCardWidgetProps> = {
  label: keys.pagebuilder.blocks.feature_card.label,
  fields: {
    eyebrow: { type: 'text', label: keys.pagebuilder.blocks.feature_card.eyebrow },
    title: { type: 'text', label: keys.pagebuilder.blocks.common.title },
    description: { type: 'textarea', label: keys.pagebuilder.blocks.common.description },
    imageUrl: createImageField(mediaLibraryAdapter, keys.pagebuilder.blocks.feature_card.image_url),
    imageAlt: { type: 'text', label: keys.pagebuilder.blocks.common.image_alt },
    linkLabel: { type: 'text', label: keys.pagebuilder.blocks.feature_card.link_label },
    linkHref: { type: 'text', label: keys.pagebuilder.blocks.feature_card.link_href },
  },
  defaultProps: {
    eyebrow: 'Featured',
    title: 'A great looking card',
    description: 'Pair an image with text and a clear call to action.',
    imageUrl: '',
    imageAlt: '',
    linkLabel: 'Read more',
    linkHref: '#',
  },
  render: ({ eyebrow, title, description, imageUrl, imageAlt, linkLabel, linkHref }) => (
    <article className="container mx-auto px-4 py-16 lg:py-20 sm:max-w-xl md:max-w-full lg:max-w-screen-xl md:px-24 lg:px-8">
      <div className="flex flex-col max-w-screen-lg overflow-hidden border rounded shadow-sm lg:flex-row sm:mx-auto">
        <div className="relative lg:w-1/2">
          {imageUrl ? (
            <img
              src={imageUrl}
              alt={imageAlt || title}
              loading="lazy"
              className="object-cover w-full lg:absolute h-80 lg:h-full"
            />
          ) : (
            <div className="w-full lg:absolute h-80 lg:h-full bg-gradient-to-br from-gray-200 to-gray-300" />
          )}
        </div>
        <div className="flex flex-col justify-center p-8 lg:p-16 lg:pl-10 lg:w-1/2">
          {eyebrow && (
            <p className="inline-block px-3 py-px mb-4 text-xs font-semibold tracking-wider uppercase rounded-full bg-teal-100 text-teal-800 w-fit">
              {renderRichText(eyebrow)}
            </p>
          )}
          {/* AccentText, not bare renderRichText: this is a display heading on
					    `--pb-display-weight`, where a plain <strong>'s relative `bolder`
					    can compute to no visible change. */}
          {title && (
            <h3
              className="mb-3 text-3xl leading-none sm:text-4xl"
              style={{
                fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
                letterSpacing: 'var(--pb-display-tracking)',
                fontFamily: 'var(--pb-display-font)',
                color: 'var(--pb-heading-color)',
              }}
            >
              <AccentText text={title} />
            </h3>
          )}
          {description && <RichTextBlock text={description} className="mb-5" />}
          {linkLabel && (
            <div className="flex items-center">
              <a
                href={linkHref || '#'}
                className="inline-flex items-center font-semibold transition-colors duration-200 text-primary-700 hover:text-primary-900"
              >
                {renderRichText(linkLabel, { allowLinks: false })}
                <svg
                  className="inline-block w-3 ml-2"
                  fill="currentColor"
                  viewBox="0 0 12 12"
                  aria-hidden="true"
                >
                  <title>Arrow right</title>
                  <path d="M9.707,5.293l-5-5A1,1,0,0,0,3.293,1.707L7.586,6,3.293,10.293a1,1,0,1,0,1.414,1.414l5-5A1,1,0,0,0,9.707,5.293Z" />
                </svg>
              </a>
            </div>
          )}
        </div>
      </div>
    </article>
  ),
};
