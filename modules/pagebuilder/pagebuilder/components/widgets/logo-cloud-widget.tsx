import type { ComponentConfig } from '@measured/puck';
import { EyebrowSplitSection } from './_internal/eyebrow-split-section';
import { renderRichText } from './_internal/rich-text';

export type LogoCloudItem = {
  src: string;
  alt: string;
  href: string;
};

export type LogoCloudWidgetProps = {
  title: string;
  eyebrow: string;
  heading: string;
  variant: 'inline' | 'grid';
  items: LogoCloudItem[];
};

export const LogoCloudWidget: ComponentConfig<LogoCloudWidgetProps> = {
  label: 'Logo cloud (partners / funders)',
  fields: {
    title: { type: 'text', label: 'Title' },
    eyebrow: { type: 'text', label: 'Eyebrow (enables section layout)' },
    heading: { type: 'text', label: 'Heading (section layout)' },
    variant: {
      type: 'select',
      label: 'Layout',
      options: [
        { label: 'Inline strip', value: 'inline' },
        { label: 'Grid', value: 'grid' },
      ],
    },
    items: {
      type: 'array',
      label: 'Logos',
      arrayFields: {
        src: { type: 'text', label: 'Image URL' },
        alt: { type: 'text', label: 'Alt text' },
        href: { type: 'text', label: 'Link (optional)' },
      },
      defaultItemProps: { src: '', alt: 'Partner logo', href: '' },
      min: 1,
      max: 24,
    },
  },
  defaultProps: {
    title: 'Funded by',
    eyebrow: '',
    heading: '',
    variant: 'inline',
    items: [
      { src: '', alt: 'Partner 1', href: '' },
      { src: '', alt: 'Partner 2', href: '' },
      { src: '', alt: 'Partner 3', href: '' },
      { src: '', alt: 'Partner 4', href: '' },
    ],
  },
  render: ({ title, eyebrow = '', heading = '', variant = 'inline', items }) => {
    if (eyebrow || heading) {
      return (
        <EyebrowSplitSection eyebrow={eyebrow} heading={heading}>
          <div
            className={
              variant === 'grid'
                ? 'grid grid-cols-2 items-center gap-x-10 gap-y-8 sm:grid-cols-3 lg:grid-cols-4'
                : 'flex flex-wrap items-center gap-x-10 gap-y-6'
            }
          >
            {items?.map((logo, idx) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; card content repeats, so a content key collides
              <LogoCloudItem key={idx} logo={logo} />
            ))}
          </div>
        </EyebrowSplitSection>
      );
    }
    return (
      // data-pb-logo-* hooks let a tenant restyle the strip from its theme
      // stylesheet (GCA: greyscale, spread edge-to-edge, bottom keyline).
      <section
        data-pb-logo-strip=""
        className="container mx-auto px-4 py-[var(--pb-section-py,3rem)] text-center sm:px-6 lg:px-8"
      >
        {title && (
          <p
            data-pb-logo-label=""
            className="text-xs font-semibold uppercase tracking-[0.2em] mb-6"
            style={{ color: 'var(--pb-body-color)' }}
          >
            {renderRichText(title)}
          </p>
        )}
        <div
          data-pb-logo-row=""
          className="flex flex-wrap items-center justify-center gap-x-10 gap-y-6"
        >
          {items?.map((logo, idx) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; card content repeats, so a content key collides
            <LogoCloudItem key={idx} logo={logo} />
          ))}
        </div>
      </section>
    );
  },
};

function LogoCloudItem({ logo }: { logo: LogoCloudItem }) {
  const img = logo.src ? (
    <img
      src={logo.src}
      alt={logo.alt}
      loading="lazy"
      className="h-10 w-auto opacity-70 hover:opacity-100 transition-opacity"
    />
  ) : (
    <div className="h-10 w-32 rounded bg-gray-100" aria-hidden="true" />
  );
  return logo.href ? (
    <a href={logo.href} className="block" aria-label={logo.alt}>
      {img}
    </a>
  ) : (
    <div>{img}</div>
  );
}
