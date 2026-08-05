import type { ComponentConfig } from '@puckeditor/core';
import { createImageField, mediaLibraryAdapter } from '../../fields';
import { cn, parseList } from '../../utils/widgetUtils';
import { RichTextBlock, renderRichText } from './_internal/rich-text';
import { ContentMedia, CTAButton, EyebrowText, Heading, Section } from './_shared';

export type FeatureShowcaseWidgetProps = {
  eyebrow: string;
  title: string;
  description: string;
  imageUrl: string;
  imageAlt: string;
  imagePosition: 'left' | 'right';
  bulletList: string;
  ctaLabel: string;
  ctaHref: string;
};

export const FeatureShowcaseWidget: ComponentConfig<FeatureShowcaseWidgetProps> = {
  label: 'Feature showcase (image + bullets)',
  fields: {
    eyebrow: { type: 'text', label: 'Eyebrow (optional)' },
    title: { type: 'text', label: 'Title' },
    description: { type: 'textarea', label: 'Description' },
    imageUrl: createImageField(mediaLibraryAdapter, 'Image URL'),
    imageAlt: { type: 'text', label: 'Image alt text' },
    imagePosition: {
      type: 'select',
      label: 'Image position',
      options: [
        { label: 'Left', value: 'left' },
        { label: 'Right', value: 'right' },
      ],
    },
    bulletList: { type: 'textarea', label: 'Bullet list (one per line)' },
    ctaLabel: { type: 'text', label: 'CTA label (optional)' },
    ctaHref: { type: 'text', label: 'CTA link (optional)' },
  },
  defaultProps: {
    eyebrow: '',
    title: 'Tools built for contributors',
    description: 'Compose your pages from reusable blocks.',
    imageUrl: '',
    imageAlt: '',
    imagePosition: 'right',
    bulletList: 'Drag and drop\nLive preview\nNo code required',
    ctaLabel: '',
    ctaHref: '',
  },
  render: ({
    eyebrow,
    title,
    description,
    imageUrl,
    imageAlt,
    imagePosition,
    bulletList,
    ctaLabel,
    ctaHref,
  }) => {
    const bullets = parseList(bulletList);
    return (
      <Section variant="default" spacing="loose">
        <div
          className={cn(
            'flex flex-col lg:flex-row items-center gap-12',
            imagePosition === 'left' ? 'lg:flex-row-reverse' : '',
          )}
        >
          <div className="flex-1">
            <EyebrowText>{eyebrow}</EyebrowText>
            <Heading as="h2" size="lg" text={title} />
            {description && (
              <RichTextBlock
                text={description}
                className="mt-4 text-lg"
                style={{ color: 'var(--pb-body-color)' }}
              />
            )}
            {bullets.length > 0 && (
              <ul className="mt-6 space-y-3">
                {bullets.map((bullet, idx) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
                  <li key={`${idx}-${bullet}`} className="flex items-start gap-3">
                    <svg
                      className="size-5 text-primary-700 flex-none mt-0.5"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                      aria-hidden="true"
                    >
                      <title>Check</title>
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                    <span>{renderRichText(bullet)}</span>
                  </li>
                ))}
              </ul>
            )}
            {ctaLabel && (
              <div className="mt-6">
                <CTAButton label={ctaLabel} href={ctaHref} variant="primary" />
              </div>
            )}
          </div>
          <div className="flex-1">
            <ContentMedia imageUrl={imageUrl} imageAlt={imageAlt} aspect="video" />
          </div>
        </div>
      </Section>
    );
  },
};
