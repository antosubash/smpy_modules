import type { ComponentConfig } from '@puckeditor/core';
import { keys, translate } from '../../utils/i18n';
import { cn } from '../../utils/widgetUtils';

export type AppStoreBadgesWidgetProps = {
  googlePlayHref: string;
  appStoreHref: string;
  googlePlaySrc: string;
  appStoreSrc: string;
  align: 'left' | 'center';
  /**
   * Start the badges at a page-grid column so they line up with an indented
   * page header above (Mowing landing hero: 2nd column). "none" keeps the
   * legacy container-edge alignment.
   */
  indent?: 'none' | '2' | '4';
};

// 12-col grid placement (gap 24px) matching the Figma page grid.
const INDENT_CLASSES: Record<'2' | '4', string> = {
  '2': 'lg:col-start-2 lg:col-span-10',
  '4': 'lg:col-start-4 lg:col-span-9',
};

export const AppStoreBadgesWidget: ComponentConfig<AppStoreBadgesWidgetProps> = {
  label: keys.pagebuilder.blocks.app_store_badges.label,
  fields: {
    googlePlayHref: {
      type: 'text',
      label: keys.pagebuilder.blocks.app_store_badges.google_play_href,
    },
    appStoreHref: { type: 'text', label: keys.pagebuilder.blocks.app_store_badges.app_store_href },
    googlePlaySrc: {
      type: 'text',
      label: keys.pagebuilder.blocks.app_store_badges.google_play_src,
    },
    appStoreSrc: { type: 'text', label: keys.pagebuilder.blocks.app_store_badges.app_store_src },
    align: {
      type: 'select',
      label: keys.pagebuilder.blocks.app_store_badges.align,
      options: [
        { label: keys.pagebuilder.blocks.app_store_badges.align_left, value: 'left' },
        { label: keys.pagebuilder.blocks.app_store_badges.align_center, value: 'center' },
      ],
    },
    indent: {
      type: 'select',
      label: keys.pagebuilder.blocks.app_store_badges.indent,
      options: [
        { label: keys.pagebuilder.blocks.app_store_badges.indent_none, value: 'none' },
        { label: keys.pagebuilder.blocks.app_store_badges.indent_2, value: '2' },
        { label: keys.pagebuilder.blocks.app_store_badges.indent_4, value: '4' },
      ],
    },
  },
  defaultProps: {
    googlePlayHref: '#',
    appStoreHref: '#',
    googlePlaySrc: '',
    appStoreSrc: '',
    align: 'left',
    indent: 'none',
  },
  render: ({
    googlePlayHref,
    appStoreHref,
    googlePlaySrc,
    appStoreSrc,
    align,
    indent = 'none',
  }) => (
    <div
      className={cn(
        'container mx-auto px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8',
        indent !== 'none' && 'lg:grid lg:grid-cols-12 lg:gap-6',
      )}
    >
      <div
        className={cn(
          'flex flex-wrap items-center gap-4',
          align === 'center' ? 'justify-center' : 'justify-start',
          indent !== 'none' && INDENT_CLASSES[indent],
        )}
      >
        {googlePlaySrc && (
          <a href={googlePlayHref} target="_blank" rel="noopener noreferrer">
            <img
              src={googlePlaySrc}
              alt={translate(keys.pagebuilder.blocks.common.google_play_alt)}
              className="h-16 w-auto"
            />
          </a>
        )}
        {appStoreSrc && (
          <a href={appStoreHref} target="_blank" rel="noopener noreferrer">
            <img
              src={appStoreSrc}
              alt={translate(keys.pagebuilder.blocks.common.app_store_alt)}
              className="h-16 w-auto"
            />
          </a>
        )}
      </div>
    </div>
  ),
};
