import type { ComponentConfig } from '@puckeditor/core';
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
  label: 'App store badges',
  fields: {
    googlePlayHref: { type: 'text', label: 'Google Play link' },
    appStoreHref: { type: 'text', label: 'App Store link' },
    googlePlaySrc: { type: 'text', label: 'Google Play badge image' },
    appStoreSrc: { type: 'text', label: 'App Store badge image' },
    align: {
      type: 'select',
      label: 'Align',
      options: [
        { label: 'Left', value: 'left' },
        { label: 'Center', value: 'center' },
      ],
    },
    indent: {
      type: 'select',
      label: 'Grid indent',
      options: [
        { label: 'None', value: 'none' },
        { label: '2nd column', value: '2' },
        { label: '4th column', value: '4' },
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
            <img src={googlePlaySrc} alt="Get it on Google Play" className="h-16 w-auto" />
          </a>
        )}
        {appStoreSrc && (
          <a href={appStoreHref} target="_blank" rel="noopener noreferrer">
            <img src={appStoreSrc} alt="Download on the App Store" className="h-16 w-auto" />
          </a>
        )}
      </div>
    </div>
  ),
};
