import type { ComponentConfig } from '@puckeditor/core';
import { createImageField, mediaLibraryAdapter } from '../../fields';
import { renderHero } from './hero-widget';

export type CenteredHeroWidgetProps = {
  title: string;
  subtitle: string;
  imageUrl: string;
  imageAlt: string;
  primaryLabel: string;
  primaryHref: string;
};

/**
 * @deprecated Use HeroWidget with imagePosition="background", align="center",
 * surface="card". Kept for backwards compatibility with saved pages.
 */
export const CenteredHeroWidget: ComponentConfig<CenteredHeroWidgetProps> = {
  label: 'Centered hero (deprecated)',
  fields: {
    title: { type: 'text', label: 'Title' },
    subtitle: { type: 'textarea', label: 'Subtitle' },
    imageUrl: createImageField(mediaLibraryAdapter, 'Background image URL'),
    imageAlt: { type: 'text', label: 'Image alt text' },
    primaryLabel: { type: 'text', label: 'Button label' },
    primaryHref: { type: 'text', label: 'Button link' },
  },
  defaultProps: {
    title: 'Welcome to GeoWiki',
    subtitle: 'Discover and contribute to global knowledge.',
    imageUrl: '',
    imageAlt: '',
    primaryLabel: 'Get started',
    primaryHref: '#',
  },
  render: (props) =>
    renderHero({
      eyebrow: '',
      title: props.title,
      subtitle: props.subtitle,
      logoUrl: '',
      logoAlt: '',
      imageUrl: props.imageUrl,
      imageAlt: props.imageAlt,
      imagePosition: 'background',
      primaryLabel: props.primaryLabel,
      primaryHref: props.primaryHref,
      secondaryLabel: '',
      secondaryHref: '',
      overlay: false,
      align: 'center',
      surface: 'card',
    }),
};
