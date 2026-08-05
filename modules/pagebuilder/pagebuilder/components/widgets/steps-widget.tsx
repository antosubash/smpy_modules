import type { ComponentConfig } from '@puckeditor/core';
import { cn } from '../../utils/widgetUtils';
import { AccentText } from './_internal/accent-text';
import { RichTextBlock, renderRichText } from './_internal/rich-text';
import { eyebrowTextStyle } from './_shared';

export type StepItem = {
  title: string;
  description: string;
  links: { label: string; href: string }[];
  showAppBadges: boolean;
};

export type StepsWidgetProps = {
  eyebrow: string;
  title: string;
  intro: string;
  surface: 'default' | 'muted';
  googlePlaySrc: string;
  appStoreSrc: string;
  items: StepItem[];
};

function ArrowUpRight() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-6 shrink-0 text-[color:var(--pb-link-arrow-color,currentColor)]"
      aria-hidden="true"
    >
      <title>Open</title>
      <path d="M7 17 17 7M9 7h8v8" />
    </svg>
  );
}

export const StepsWidget: ComponentConfig<StepsWidgetProps> = {
  label: 'Steps (how to)',
  fields: {
    eyebrow: { type: 'text', label: 'Eyebrow' },
    title: { type: 'text', label: 'Title' },
    intro: { type: 'textarea', label: 'Intro text' },
    surface: {
      type: 'select',
      label: 'Surface',
      options: [
        { label: 'Default', value: 'default' },
        { label: 'Muted', value: 'muted' },
      ],
    },
    googlePlaySrc: { type: 'text', label: 'Google Play badge image' },
    appStoreSrc: { type: 'text', label: 'App Store badge image' },
    items: {
      type: 'array',
      label: 'Steps',
      arrayFields: {
        title: { type: 'text', label: 'Step title' },
        description: { type: 'textarea', label: 'Description' },
        links: {
          type: 'array',
          label: 'Links',
          arrayFields: {
            label: { type: 'text', label: 'Label' },
            href: { type: 'text', label: 'Link' },
          },
          defaultItemProps: { label: 'Link', href: '#' },
        },
        showAppBadges: {
          type: 'radio',
          label: 'Show app store badges',
          options: [
            { label: 'Yes', value: true },
            { label: 'No', value: false },
          ],
        },
      },
      defaultItemProps: {
        title: 'Step',
        description: '',
        links: [],
        showAppBadges: false,
      },
      min: 1,
      max: 12,
    },
  },
  defaultProps: {
    eyebrow: '',
    title: 'How to Contribute Data',
    intro: '',
    surface: 'muted',
    googlePlaySrc: '',
    appStoreSrc: '',
    items: [
      {
        title: '1. Download Geo-Quest',
        description: 'Get the app from the Google Play or Apple App Store.',
        links: [],
        showAppBadges: true,
      },
    ],
  },
  // Muted surface renders as a rounded card spanning the container (Mowing
  // Figma "How to Contribute Data": 80px vertical padding, eyebrow inset 48px).
  // Column geometry is tenant-tunable via `--pb-split-cols`/`--pb-split-gap`
  // (Mowing aligns the content to the 4th page-grid column); the 1fr/2fr
  // fallback keeps tenants without the tokens unchanged.
  render: ({ eyebrow, title, intro, surface, googlePlaySrc, appStoreSrc, items }) => (
    <section className="container mx-auto px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8">
      <div
        className={cn(
          'grid gap-y-6 md:grid-cols-[var(--pb-split-cols,1fr_2fr)] md:gap-x-[var(--pb-split-gap,2rem)]',
          surface === 'muted' &&
            'rounded-[12px] bg-[var(--pb-surface-muted,#f3f3f4)] px-8 py-12 lg:px-0 lg:py-20',
        )}
      >
        {eyebrow && (
          <p
            className={cn(surface === 'muted' && 'lg:pl-12')}
            style={{
              // Eyebrow size/weight/case/tracking are theme-driven; the
              // fallbacks keep today's look for tenants that don't set them.
              ...eyebrowTextStyle('1.125rem', '400'),
              color: 'var(--pb-heading-color,#161728)',
            }}
          >
            {renderRichText(eyebrow)}
          </p>
        )}
        <div className={cn('max-w-2xl', !eyebrow && 'md:col-span-2')}>
          {title && (
            <h2
              className="leading-tight"
              style={{
                color: 'var(--pb-heading-color)',
                fontWeight: 'var(--pb-display-weight)',
                fontFamily: 'var(--pb-display-font)',
                fontSize: 'var(--pb-heading-md, clamp(1.875rem, 1.3rem + 1.4vw, 2.5rem))',
              }}
            >
              {renderRichText(title)}
            </h2>
          )}
          {intro && (
            <RichTextBlock
              text={intro}
              className="mt-5 text-lg leading-[var(--pb-body-leading,1.625)] text-[var(--pb-body-color,#686873)]"
            />
          )}
          <div className="mt-8 flex flex-col gap-10">
            {items.map((step, idx) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
              <div key={idx}>
                <h3 className="text-xl font-semibold" style={{ color: 'var(--pb-heading-color)' }}>
                  {renderRichText(step.title)}
                </h3>
                {step.description && (
                  // Inline AccentText, not RichTextBlock: step copy uses the
                  // tenant accent treatment for `*word*` (Mowing's Figma), and
                  // `whitespace-pre-line` keeps single newlines. Bullet lists
                  // are deliberately not supported here.
                  <p className="mt-2 whitespace-pre-line text-lg leading-[var(--pb-body-leading,1.625)] text-[var(--pb-body-color,#686873)]">
                    <AccentText text={step.description} />
                  </p>
                )}
                {step.showAppBadges && (googlePlaySrc || appStoreSrc) && (
                  <div className="mt-5 flex flex-wrap gap-4">
                    {googlePlaySrc && (
                      <img
                        src={googlePlaySrc}
                        alt="Get it on Google Play"
                        className="h-16 w-auto"
                      />
                    )}
                    {appStoreSrc && (
                      <img
                        src={appStoreSrc}
                        alt="Download on the App Store"
                        className="h-16 w-auto"
                      />
                    )}
                  </div>
                )}
                {step.links?.length > 0 && (
                  <div className="mt-5">
                    {step.links.map((l, i) => (
                      <a
                        // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; content repeats, so a content key collides
                        key={i}
                        href={l.href}
                        className="flex items-center justify-between gap-4 border-b border-[var(--border,#dcdcdf)] py-4 text-lg font-medium text-[color:var(--pb-heading-color,#161728)] transition-colors hover:text-[color:var(--pb-link-hover-color,var(--pb-heading-color,#161728))]"
                      >
                        {renderRichText(l.label, { allowLinks: false })}
                        <ArrowUpRight />
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  ),
};
