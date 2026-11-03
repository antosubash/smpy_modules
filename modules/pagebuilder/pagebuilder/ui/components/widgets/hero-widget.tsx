import type { ComponentConfig } from '@puckeditor/core';
import { createCheckboxField, createImageField, mediaLibraryAdapter } from '../../fields';
import { keys } from '../../utils/i18n';
import { imageSrcsetField, resolveImageSrcset } from './_shared';
import type { HeroWidgetProps } from './hero-widget-props';

export type { HeroWidgetProps } from './hero-widget-props';

// Exported so CenteredHeroWidget can render through it without smuggling
// Puck's ComponentConfig.render signature past the type system.
import { renderHero } from './hero-render';

export const HeroWidget: ComponentConfig<HeroWidgetProps> = {
  label: keys.pagebuilder.blocks.hero.label,
  fields: {
    eyebrow: { type: 'text', label: keys.pagebuilder.blocks.hero.eyebrow },
    title: { type: 'text', label: keys.pagebuilder.blocks.common.title },
    subtitle: { type: 'textarea', label: keys.pagebuilder.blocks.common.subtitle },
    logoUrl: createImageField(mediaLibraryAdapter, keys.pagebuilder.blocks.hero.logo_url),
    logoAlt: { type: 'text', label: keys.pagebuilder.blocks.common.logo_alt },
    imageUrl: createImageField(mediaLibraryAdapter, keys.pagebuilder.blocks.hero.image_url),
    imageAlt: { type: 'text', label: keys.pagebuilder.blocks.common.image_alt },
    imageSrcset: imageSrcsetField,
    imageMaskUrl: {
      type: 'text',
      label: keys.pagebuilder.blocks.hero.image_mask_url,
    },
    imageShape: {
      type: 'select',
      label: keys.pagebuilder.blocks.hero.image_shape,
      options: [
        { label: keys.pagebuilder.blocks.hero.image_shape_rounded, value: 'rounded' },
        { label: keys.pagebuilder.blocks.hero.image_shape_native, value: 'native' },
      ],
    },
    imagePosition: {
      type: 'select',
      label: keys.pagebuilder.blocks.hero.image_position,
      options: [
        { label: keys.pagebuilder.blocks.hero.image_position_background, value: 'background' },
        { label: keys.pagebuilder.blocks.hero.image_position_right, value: 'right' },
        { label: keys.pagebuilder.blocks.hero.image_position_left, value: 'left' },
      ],
    },
    primaryLabel: { type: 'text', label: keys.pagebuilder.blocks.hero.primary_label },
    primaryHref: { type: 'text', label: keys.pagebuilder.blocks.hero.primary_href },
    secondaryLabel: { type: 'text', label: keys.pagebuilder.blocks.hero.secondary_label },
    secondaryHref: { type: 'text', label: keys.pagebuilder.blocks.hero.secondary_href },
    overlay: createCheckboxField(keys.pagebuilder.blocks.hero.overlay),
    align: {
      type: 'select',
      label: keys.pagebuilder.blocks.common.align,
      options: [
        { label: keys.pagebuilder.blocks.common.align_left, value: 'left' },
        { label: keys.pagebuilder.blocks.common.align_center, value: 'center' },
      ],
    },
    surface: {
      type: 'select',
      label: keys.pagebuilder.blocks.hero.surface,
      options: [
        { label: keys.pagebuilder.blocks.hero.surface_plain, value: 'plain' },
        { label: keys.pagebuilder.blocks.hero.surface_card, value: 'card' },
      ],
    },
  },
  defaultProps: {
    eyebrow: '',
    title: 'Open knowledge, *mapped*.',
    subtitle: "Discover and contribute to the world's largest community-maintained gazetteer.",
    logoUrl: '',
    logoAlt: '',
    imageUrl: '',
    imageAlt: '',
    imageSrcset: '',
    imageMaskUrl: '',
    imageShape: 'rounded',
    imagePosition: 'background',
    primaryLabel: 'Get started',
    primaryHref: '#',
    secondaryLabel: 'Learn more',
    secondaryHref: '#',
    overlay: true,
    align: 'center',
    surface: 'plain',
  },
  resolveData: resolveImageSrcset,
  render: renderHero,
};
