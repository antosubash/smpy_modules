import type { ComponentConfig } from '@puckeditor/core';
import { createImageField, mediaLibraryAdapter } from '../../fields';
import { keys } from '../../utils/i18n';
import { renderRichText } from './_internal/rich-text';

export type SocialBannerLink = {
  label: string;
  href: string;
  iconUrl: string;
};

export type SocialBannerWidgetProps = {
  heading: string;
  subheading: string;
  links: SocialBannerLink[];
};

export const SocialBannerWidget: ComponentConfig<SocialBannerWidgetProps> = {
  label: keys.pagebuilder.blocks.social_banner.label,
  fields: {
    heading: { type: 'text', label: keys.pagebuilder.blocks.common.heading },
    subheading: { type: 'text', label: keys.pagebuilder.blocks.common.subheading },
    links: {
      type: 'array',
      label: keys.pagebuilder.blocks.social_banner.links,
      arrayFields: {
        label: { type: 'text', label: keys.pagebuilder.blocks.social_banner.links_label },
        href: { type: 'text', label: keys.pagebuilder.blocks.social_banner.links_href },
        iconUrl: createImageField(
          mediaLibraryAdapter,
          keys.pagebuilder.blocks.social_banner.links_icon_url,
        ),
      },
      defaultItemProps: {
        label: 'Twitter',
        href: '#',
        iconUrl: '',
      },
      min: 1,
      max: 10,
    },
  },
  defaultProps: {
    heading: 'Follow us',
    subheading: 'Stay up to date with the latest news.',
    links: [
      { label: 'Twitter', href: '#', iconUrl: '' },
      { label: 'GitHub', href: '#', iconUrl: '' },
    ],
  },
  render: ({ heading, subheading, links }) => (
    <section className="container mx-auto px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8">
      <div className="rounded-2xl bg-[var(--secondary,#1a353e)] px-6 py-14 text-center text-white sm:py-16">
        {heading && (
          <h2
            className="mx-auto max-w-3xl leading-tight"
            style={{
              fontFamily: 'var(--pb-display-font)',
              fontWeight: 'var(--pb-display-weight)',
              fontSize: 'var(--pb-heading-lg, clamp(1.875rem, 1.3rem + 2.5vw, 3rem))',
            }}
          >
            {renderRichText(heading)}
          </h2>
        )}
        {subheading && <p className="mt-3 text-lg text-white/80">{renderRichText(subheading)}</p>}
        {links && links.length > 0 && (
          <div className="mt-6 flex flex-wrap items-center justify-center gap-8">
            {links.map((link, idx) => (
              <a
                // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
                key={idx}
                href={link.href || '#'}
                className="inline-flex items-center gap-2 text-xl font-semibold transition-opacity hover:opacity-80"
              >
                {link.iconUrl && (
                  <img src={link.iconUrl} alt="" loading="lazy" className="size-5 object-contain" />
                )}
                {renderRichText(link.label, { allowLinks: false })}
              </a>
            ))}
          </div>
        )}
      </div>
    </section>
  ),
};
