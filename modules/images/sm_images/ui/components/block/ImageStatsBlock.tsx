/**
 * `ImageStats` Puck block: up to six live numbers about public collections
 * (images, located images, collections). Config side; the render is
 * `ImageStatsRender.tsx`. Collections are offered from the admin list inside
 * the editor only; the public page never calls it.
 */

import type { ComponentConfig } from '@puckeditor/core';
import {
  createImageField,
  mediaLibraryAdapter,
} from '@simple-module-py/pagebuilder/pagebuilder/ui/fields';

import { keys, type Translate, translate } from '../../utils/i18n';
import { publicCollections } from './ImageGalleryBlock';
import {
  clampStatItems,
  type ImageStatItem,
  type ImageStatsProps,
  ImageStatsRender,
  STAT_ITEMS_MAX,
} from './ImageStatsRender';

export type { ImageStatItem };
export { clampStatItems, ImageStatsRender };

type Option = { label: string; value: string };
type BlockFields = NonNullable<ComponentConfig<ImageStatsProps>['fields']>;

/** A new block's first item, and every item added to it. */
const DEFAULT_ITEM: ImageStatItem = {
  metric: 'images',
  collection: '',
  label: 'Images',
  prefix: '',
  suffix: '',
};

function buildFields(tr: Translate, collections: Option[]): BlockFields {
  const k = keys.images.stats;
  return {
    title: { type: 'text', label: tr(k.title) },
    subtitle: { type: 'textarea', label: tr(k.subtitle) },
    items: {
      type: 'array',
      label: tr(k.items),
      arrayFields: {
        label: { type: 'text', label: tr(k.item_label) },
        metric: {
          type: 'select',
          label: tr(k.item_metric),
          options: [
            { label: tr(k.item_metric_images), value: 'images' },
            { label: tr(k.item_metric_located), value: 'located' },
            { label: tr(k.item_metric_collections), value: 'collections' },
          ],
        },
        collection: {
          type: 'select',
          label: tr(k.item_collection),
          options: [{ label: tr(k.item_collection_all), value: '' }, ...collections],
        },
        prefix: { type: 'text', label: tr(k.item_prefix) },
        suffix: { type: 'text', label: tr(k.item_suffix) },
        iconUrl: createImageField(mediaLibraryAdapter, tr(k.item_icon)),
      },
      defaultItemProps: DEFAULT_ITEM,
      min: 1,
      max: STAT_ITEMS_MAX,
    },
    surface: {
      type: 'select',
      label: tr(k.surface),
      options: [
        { label: tr(k.surface_default), value: 'default' },
        { label: tr(k.surface_lime), value: 'lime' },
        { label: tr(k.surface_cards), value: 'cards' },
      ],
    },
  };
}

/** The picker load in flight; the next `resolveFields` supersedes it. */
let picker: AbortController | null = null;

export const ImageStatsBlock: ComponentConfig<ImageStatsProps> = {
  label: keys.images.stats.label,
  // Labels are catalogue keys here (pagebuilder's `localizeConfig` resolves
  // them); `resolveFields` supplies translated ones once the editor runs.
  fields: buildFields((key) => key, []),
  defaultProps: {
    title: '',
    subtitle: '',
    surface: 'default',
    items: [{ ...DEFAULT_ITEM }],
  },
  resolveFields: async () => {
    picker?.abort();
    picker = new AbortController();
    return buildFields(translate, await publicCollections(picker.signal));
  },
  // Once on load, never per keystroke.
  resolveData: ({ props }, { trigger }) =>
    trigger === 'load' ? { props: { ...props, items: clampStatItems(props.items) } } : { props },
  render: ImageStatsRender,
};
