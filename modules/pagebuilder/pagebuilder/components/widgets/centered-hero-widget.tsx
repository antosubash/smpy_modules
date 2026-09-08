import type { ComponentConfig } from '@puckeditor/core';
import { createImageField, mediaLibraryAdapter } from '../../fields';
import { keys } from '../../utils/i18n';
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
  label: keys.pagebuilder.blocks.centered_hero.label,
  fields: {
    title: { type: 'text', label: keys.pagebuilder.blocks.common.title },
    subtitle: { type: 'textarea', label: keys.pagebuilder.blocks.common.subtitle },
    imageUrl: createImageField(
      mediaLibraryAdapter,
      keys.pagebuilder.blocks.centered_hero.image_url,
    ),
    imageAlt: { type: 'text', label: keys.pagebuilder.blocks.common.image_alt },
    primaryLabel: { type: 'text', label: keys.pagebuilder.blocks.centered_hero.primary_label },
    primaryHref: { type: 'text', label: keys.pagebuilder.blocks.centered_hero.primary_href },
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
