import type { ComponentConfig } from '@puckeditor/core';
import { cn } from '../../utils/widgetUtils';
import { renderRichText } from './_internal/rich-text';

export type ColoredActionListItem = {
  title: string;
  href: string;
};

export type ColoredActionListWidgetProps = {
  eyebrow: string;
  heading: string;
  tone: 'green' | 'purple' | 'neutral';
  items: ColoredActionListItem[];
};

const TONE_CLASS: Record<ColoredActionListWidgetProps['tone'], string> = {
  green: 'bg-primary-700 text-white',
  purple: 'bg-[#eeedff] text-gray-900',
  neutral: 'bg-gray-100 text-gray-900',
};

const TONE_DIVIDER: Record<ColoredActionListWidgetProps['tone'], string> = {
  green: 'border-white/20',
  purple: 'border-black/10',
  neutral: 'border-black/10',
};

export const ColoredActionListWidget: ComponentConfig<ColoredActionListWidgetProps> = {
  label: 'Colored action list (tinted block)',
  fields: {
    eyebrow: { type: 'text', label: 'Eyebrow' },
    heading: { type: 'text', label: 'Heading' },
    tone: {
      type: 'select',
      label: 'Tone',
      options: [
        { label: 'Green', value: 'green' },
        { label: 'Purple', value: 'purple' },
        { label: 'Neutral', value: 'neutral' },
      ],
    },
    items: {
      type: 'array',
      label: 'Items',
      arrayFields: {
        title: { type: 'text', label: 'Title' },
        href: { type: 'text', label: 'Link' },
      },
      defaultItemProps: { title: 'Action', href: '#' },
      min: 1,
      max: 20,
    },
  },
  defaultProps: {
    eyebrow: 'Get Started',
    heading: 'Get started with our Farmer Cluster guidelines',
    tone: 'green',
    items: [
      { title: 'Farmer Cluster: An Overview', href: '#' },
      { title: 'Starting a Farmer Cluster', href: '#' },
      { title: 'Managing a Farmer Cluster', href: '#' },
      { title: 'Farmer Cluster Communication Guidelines', href: '#' },
      { title: 'Stakeholder Engagement Guidelines', href: '#' },
      { title: 'Monitoring Biodiversity', href: '#' },
    ],
  },
  render: ({ eyebrow, heading, tone, items }) => (
    <section className="container mx-auto px-4 py-6">
      <div className={cn('rounded-xl p-6 sm:p-10', TONE_CLASS[tone])}>
        {eyebrow && (
          <p className="text-xs font-semibold uppercase tracking-wider opacity-80">
            {renderRichText(eyebrow)}
          </p>
        )}
        {heading && (
          <h2 className="mt-2 text-2xl sm:text-3xl font-light leading-tight">
            {renderRichText(heading)}
          </h2>
        )}
        {items?.length > 0 && (
          <ul className={cn('mt-6 divide-y rounded-lg overflow-hidden border', TONE_DIVIDER[tone])}>
            {items.map((item, idx) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
              <li key={idx}>
                <a
                  href={item.href || '#'}
                  className={cn(
                    'flex items-center justify-between px-4 py-3 text-base font-medium transition-colors',
                    tone === 'green' ? 'hover:bg-white/10' : 'hover:bg-black/5',
                  )}
                >
                  {renderRichText(item.title || '', { allowLinks: false })}
                  <svg
                    className="size-4 opacity-80"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                    aria-hidden="true"
                  >
                    <title>Open</title>
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M9 5l7 7-7 7"
                    />
                  </svg>
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  ),
};
