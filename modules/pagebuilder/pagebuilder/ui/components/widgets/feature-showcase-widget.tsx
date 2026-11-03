import type { ComponentConfig } from '@puckeditor/core';
import { createImageField, mediaLibraryAdapter } from '../../fields';
import { keys } from '../../utils/i18n';
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
  label: keys.pagebuilder.blocks.feature_showcase.label,
  fields: {
    eyebrow: { type: 'text', label: keys.pagebuilder.blocks.feature_showcase.eyebrow },
    title: { type: 'text', label: keys.pagebuilder.blocks.common.title },
    description: { type: 'textarea', label: keys.pagebuilder.blocks.common.description },
    imageUrl: createImageField(
      mediaLibraryAdapter,
      keys.pagebuilder.blocks.feature_showcase.image_url,
    ),
    imageAlt: { type: 'text', label: keys.pagebuilder.blocks.common.image_alt },
    imagePosition: {
      type: 'select',
      label: keys.pagebuilder.blocks.feature_showcase.image_position,
      options: [
        { label: keys.pagebuilder.blocks.feature_showcase.image_position_left, value: 'left' },
        { label: keys.pagebuilder.blocks.feature_showcase.image_position_right, value: 'right' },
      ],
    },
    bulletList: { type: 'textarea', label: keys.pagebuilder.blocks.feature_showcase.bullet_list },
    ctaLabel: { type: 'text', label: keys.pagebuilder.blocks.feature_showcase.cta_label },
    ctaHref: { type: 'text', label: keys.pagebuilder.blocks.feature_showcase.cta_href },
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
