import type { ComponentConfig } from '@puckeditor/core';
import { type CSSProperties, useId } from 'react';
import { createImageField, mediaLibraryAdapter } from '../../fields';
import { AccentText } from './_internal/accent-text';
import { RichTextBlock, renderRichText } from './_internal/rich-text';

export type NewsletterWidgetProps = {
  heading: string;
  subheading: string;
  placeholder: string;
  buttonLabel: string;
  /**
   * Consent sentence rendered beside a required checkbox. `*word*` marks the
   * segment that links to `privacyHref` (same convention as the contact form's
   * terms label). Empty hides the row.
   */
  privacyText: string;
  privacyHref: string;
  /** Optional photo backdrop — the band renders full-bleed with white text. */
  imageUrl: string;
  imageAlt: string;
};

export const NewsletterWidget: ComponentConfig<NewsletterWidgetProps> = {
  label: 'Newsletter signup',
  fields: {
    heading: { type: 'text', label: 'Heading' },
    subheading: { type: 'textarea', label: 'Subheading' },
    placeholder: { type: 'text', label: 'Email placeholder' },
    buttonLabel: { type: 'text', label: 'Button label' },
    privacyText: {
      type: 'text',
      label: 'Consent text (*word* links to the privacy link)',
    },
    privacyHref: { type: 'text', label: 'Privacy link' },
    imageUrl: createImageField(mediaLibraryAdapter, 'Background image (optional)'),
    imageAlt: { type: 'text', label: 'Background image alt text' },
  },
  defaultProps: {
    heading: 'Subscribe to our newsletter',
    subheading: 'Get the latest updates straight to your inbox.',
    placeholder: 'you@example.com',
    buttonLabel: 'Subscribe',
    privacyText: 'I have read and expressly agree to the *privacy policy*.',
    privacyHref: '#',
    imageUrl: '',
    imageAlt: '',
  },
  render: (props) => <NewsletterRender {...props} />,
};

function NewsletterRender({
  heading,
  subheading,
  placeholder,
  buttonLabel,
  privacyText,
  privacyHref,
  imageUrl,
  imageAlt,
}: NewsletterWidgetProps) {
  const emailId = useId();
  const termsId = useId();
  const hasImage = Boolean(imageUrl);
  return (
    <section className="container mx-auto px-4 sm:px-6 lg:px-8">
      {/* One left-hand column (heading → body → form → consent), as the Figma:
			    the form used to sit in a second column on the right, which pushed it
			    over the busiest part of the photo and squashed the band. */}
      {/* `--pb-newsletter-min-h` lets a tenant pin the band to its Figma
			    height (BioGarden: 800px, which also gives the photo the taller
			    crop the design shows); unset it collapses to content height, as
			    before. The content stays vertically centred within it. */}
      {/* `data-pb-newsletter-*` attributes are styling hooks for tenant design packs
			    (no styles of their own) — kept in lockstep with the app's override
			    copy of this widget (features/cms/widgets/newsletter-widget.tsx). */}
      <div
        data-pb-newsletter-band=""
        className={
          hasImage
            ? 'relative isolate flex min-h-[var(--pb-newsletter-min-h,0)] flex-col justify-center overflow-hidden rounded-[var(--pb-newsletter-radius,0.75rem)] py-12 px-6 sm:px-8 lg:py-24 lg:px-10'
            : 'border flex min-h-[var(--pb-newsletter-min-h,0)] flex-col justify-center rounded-[var(--pb-newsletter-radius,0.75rem)] py-12 px-6 sm:px-8 lg:py-24 lg:px-10'
        }
      >
        {hasImage && (
          <>
            <img
              src={imageUrl}
              alt={imageAlt || ''}
              loading="lazy"
              className="absolute inset-0 -z-10 size-full object-cover"
            />
            <div className="absolute inset-0 -z-10 bg-black/30" aria-hidden />
          </>
        )}
        <div className="max-w-[var(--pb-newsletter-col,37rem)]">
          {heading && (
            <h2
              data-pb-newsletter-heading=""
              className="text-3xl sm:text-4xl"
              style={{
                fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
                letterSpacing: 'var(--pb-display-tracking)',
                fontFamily: 'var(--pb-display-font)',
                color: hasImage ? 'var(--pb-surface-contrast, #ffffff)' : 'var(--pb-heading-color)',
              }}
            >
              <AccentText text={heading} />
            </h2>
          )}
          {subheading && (
            <RichTextBlock
              data-pb-newsletter-sub=""
              text={subheading}
              className={
                hasImage
                  ? 'mt-3 max-w-3xl text-lg leading-6 opacity-90'
                  : 'mt-3 max-w-3xl text-lg leading-6'
              }
              style={
                hasImage
                  ? { color: 'var(--pb-surface-contrast, #ffffff)' }
                  : { color: 'var(--pb-body-color)' }
              }
            />
          )}
          <form className="pt-8">
            <div className="flex flex-col gap-4 sm:flex-row">
              <label htmlFor={emailId} className="sr-only">
                {placeholder || 'Email address'}
              </label>
              <input
                id={emailId}
                className={
                  hasImage
                    ? 'mt-1 block w-full rounded-full border border-transparent bg-white/90 shadow-sm py-2.5 px-4 text-gray-900 placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-white/70 sm:text-sm'
                    : 'mt-1 bg-gray-100 dark:bg-gray-800 block w-full border border-gray-300 dark:border-gray-700 rounded-md shadow-sm py-2 px-3 focus:outline-none focus:ring-primary-500 focus:border-primary-700 sm:text-sm'
                }
                type="email"
                name="email"
                placeholder={placeholder}
              />
              <button
                type="submit"
                className={
                  hasImage
                    ? 'inline-flex items-center justify-center py-2.5 px-6 rounded-full border font-medium whitespace-nowrap transition-colors hover:bg-white/10'
                    : 'inline-flex items-center justify-center py-2 px-5 rounded-md bg-primary-700 hover:bg-primary-800 text-white font-medium whitespace-nowrap'
                }
                style={
                  hasImage
                    ? {
                        borderColor: 'var(--pb-surface-contrast, #ffffff)',
                        color: 'var(--pb-surface-contrast, #ffffff)',
                        backgroundColor: 'transparent',
                      }
                    : undefined
                }
              >
                {renderRichText(buttonLabel, { allowLinks: false })}
                {/* Trailing arrow, off by default (`--pb-button-arrow-display`). */}
                <span
                  aria-hidden="true"
                  className="ml-2 [display:var(--pb-button-arrow-display,none)]"
                >
                  →
                </span>
              </button>
            </div>
            {/* Inside the <form> so `required` actually gates submission. */}
            {privacyText && (
              <div className="mt-5 flex items-start gap-2">
                <input
                  id={termsId}
                  type="checkbox"
                  required
                  className="mt-1"
                  style={{
                    accentColor: hasImage
                      ? 'var(--pb-surface-contrast, #ffffff)'
                      : 'var(--primary)',
                  }}
                />
                <label
                  htmlFor={termsId}
                  className={hasImage ? 'text-sm opacity-85' : 'text-sm'}
                  style={
                    hasImage
                      ? { color: 'var(--pb-surface-contrast, #ffffff)' }
                      : { color: 'var(--pb-body-color)' }
                  }
                >
                  {/* `*word*` marks the privacy link, matching the contact
									    form's terms label convention. */}
                  {privacyText.split(/(\*[^*]+\*)/g).map((part, i) =>
                    part.startsWith('*') && part.endsWith('*') && part.length > 2 ? (
                      <a
                        // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
                        key={i}
                        href={privacyHref || '#'}
                        className="cursor-pointer font-semibold underline"
                      >
                        {part.slice(1, -1)}
                      </a>
                    ) : (
                      part
                    ),
                  )}
                </label>
              </div>
            )}
          </form>
        </div>
      </div>
    </section>
  );
}
