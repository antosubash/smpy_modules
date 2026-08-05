import type { ComponentConfig } from '@puckeditor/core';
import { RichTextBlock, renderRichText } from './_internal/rich-text';

export type SignupBannerWidgetProps = {
  heading: string;
  subheading: string;
  primaryLabel: string;
  primaryHref: string;
};

export const SignupBannerWidget: ComponentConfig<SignupBannerWidgetProps> = {
  label: 'Signup banner',
  fields: {
    heading: { type: 'text', label: 'Heading' },
    subheading: { type: 'textarea', label: 'Subheading' },
    primaryLabel: { type: 'text', label: 'Button label' },
    primaryHref: { type: 'text', label: 'Button link' },
  },
  defaultProps: {
    heading: 'Join us today',
    subheading: 'Create a free account in seconds.',
    primaryLabel: 'Sign up',
    primaryHref: '#',
  },
  render: ({ heading, subheading, primaryLabel, primaryHref }) => (
    <section className="rounded-xl bg-gray-900 text-white">
      <div className="container mx-auto py-12 px-6 sm:px-10 text-center">
        {heading && (
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-light tracking-tight">
            {renderRichText(heading)}
          </h2>
        )}
        {subheading && (
          <RichTextBlock
            text={subheading}
            className="mt-3 text-lg text-gray-300 max-w-2xl mx-auto"
          />
        )}
        {primaryLabel && (
          <a
            href={primaryHref || '#'}
            className="mt-8 inline-flex items-center justify-center px-6 py-3 rounded-md bg-primary-700 hover:bg-primary-800 text-white font-medium transition-colors"
          >
            {renderRichText(primaryLabel, { allowLinks: false })}
          </a>
        )}
      </div>
    </section>
  ),
};
