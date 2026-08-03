import type { ComponentConfig } from '@measured/puck';
import type { CSSProperties } from 'react';
import { cn } from '../../utils/widgetUtils';
import { RichTextBlock, renderRichText } from './_internal/rich-text';

export type StatItem = {
  value: string;
  label: string;
  iconUrl?: string;
};

export type StatsWidgetProps = {
  title: string;
  subtitle: string;
  items: StatItem[];
  surface: 'default' | 'lime' | 'cards';
};

// Display tokens for the title/numbers — weight/tracking/font come from the
// per-tenant page-builder theme (see styles.css `:root` for Recodo defaults and
// `.gca-root` for the GCA overrides). Color is overridden in the lime surface.
const DISPLAY_STYLE: CSSProperties = {
  fontWeight: 'var(--pb-display-weight)' as CSSProperties['fontWeight'],
  letterSpacing: 'var(--pb-display-tracking)',
  fontFamily: 'var(--pb-display-font)',
};

export const StatsWidget: ComponentConfig<StatsWidgetProps> = {
  label: 'Statistics',
  fields: {
    title: { type: 'text', label: 'Title' },
    subtitle: { type: 'textarea', label: 'Subtitle' },
    items: {
      type: 'array',
      label: 'Statistics',
      arrayFields: {
        value: { type: 'text', label: 'Value' },
        label: { type: 'text', label: 'Label' },
        iconUrl: { type: 'text', label: 'Icon image (optional)' },
      },
      defaultItemProps: { value: '100+', label: 'Item' },
      min: 1,
      max: 12,
    },
    surface: {
      type: 'select',
      label: 'Surface',
      options: [
        { label: 'Default', value: 'default' },
        { label: 'Lime', value: 'lime' },
        { label: 'Cards', value: 'cards' },
      ],
    },
  },
  defaultProps: {
    title: "We're trusted by thousands",
    subtitle: 'Numbers that speak for themselves',
    items: [
      { value: '10K+', label: 'Users' },
      { value: '99.9%', label: 'Uptime' },
      { value: '24/7', label: 'Support' },
    ],
    surface: 'default',
  },
  render: (props) => <StatsView {...props} />,
};

// Presentational stats — shared by the static base widget (above) and the app's
// live, data-driven override, so both render identically.
export function StatsView({ title, subtitle, items, surface }: StatsWidgetProps) {
  const count = items?.length ?? 0;

  if (surface === 'cards') {
    return (
      <section className="container mx-auto px-4 py-[var(--pb-section-py,3rem)] sm:px-6 lg:px-8">
        {count > 0 && (
          <dl className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((stat, idx) => (
              <div
                // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; card content repeats, so a content key collides
                key={idx}
                className="relative flex min-h-[142px] flex-col justify-center rounded-[12px] border border-[var(--border,#dcdcdf)] bg-[var(--pb-surface,#ffffff)] px-6 py-5"
              >
                {stat.iconUrl && (
                  <span className="absolute right-6 top-6 flex size-14 items-center justify-center rounded-lg bg-[var(--secondary,#42547e)]">
                    <img src={stat.iconUrl} alt="" className="size-8 object-contain" />
                  </span>
                )}
                <dd
                  className="text-[2.75rem] sm:text-[3.5rem] leading-none font-semibold"
                  style={{
                    fontFamily: 'var(--pb-display-font)',
                    color: 'var(--pb-heading-color,#161728)',
                  }}
                >
                  {renderRichText(stat.value)}
                </dd>
                <dt className="mt-3 text-base font-semibold text-[var(--pb-accent,#fa6e25)]">
                  {renderRichText(stat.label)}
                </dt>
              </div>
            ))}
          </dl>
        )}
      </section>
    );
  }

  if (surface === 'lime') {
    // GCA "Stats item-5 column": left-aligned values and labels on the lime
    // band, one line per value, thin ink dividers (SNAG_007).
    return (
      <section className="container mx-auto py-[var(--pb-section-py,3rem)] px-4 sm:px-6 lg:px-8">
        {count > 0 && (
          <div className="rounded-xl bg-[#d8ec29] px-6 py-8 lg:px-8 lg:py-10">
            <dl className="flex flex-col justify-center sm:flex-row sm:flex-wrap lg:flex-nowrap">
              {items.map((stat, idx) => (
                <div
                  // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; card content repeats, so a content key collides
                  key={idx}
                  className={cn(
                    'flex flex-1 flex-col px-4 py-4 sm:px-6',
                    idx > 0 ? 'sm:border-l sm:border-[#1a353e]/20' : '',
                  )}
                >
                  <dd
                    className="order-1 text-[1.875rem] leading-[1.2] text-[#1a353e] sm:text-[2.125rem] xl:whitespace-nowrap"
                    style={DISPLAY_STYLE}
                  >
                    {renderRichText(stat.value)}
                  </dd>
                  <dt className="order-2 mt-2 text-[18px] text-[#1a353e]">
                    {renderRichText(stat.label)}
                  </dt>
                </div>
              ))}
            </dl>
          </div>
        )}
      </section>
    );
  }

  return (
    <section className="container mx-auto py-[var(--pb-section-py,3rem)] px-4 sm:px-6 lg:px-8 font-semibold">
      <div className="max-w-4xl mx-auto text-center">
        {title && (
          <h2
            className="text-3xl sm:text-4xl"
            style={{
              ...DISPLAY_STYLE,
              color: 'var(--pb-heading-color)',
            }}
          >
            {renderRichText(title)}
          </h2>
        )}
        {subtitle && <RichTextBlock text={subtitle} className="mt-3 text-xl sm:mt-4" />}
      </div>
      {count > 0 && (
        <dl
          className="mt-10 text-center max-w-3xl mx-auto grid gap-8 grid-cols-1 stats-grid"
          style={
            {
              '--stats-cols': count,
            } as React.CSSProperties
          }
        >
          {items.map((stat, idx) => (
            <div
              // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; card content repeats, so a content key collides
              key={idx}
              className="flex flex-col items-center"
            >
              {stat.iconUrl && (
                <img src={stat.iconUrl} alt="" className="mx-auto mb-3 h-10 w-10 object-contain" />
              )}
              <dt
                className="order-2 mt-2 text-lg leading-6 font-medium"
                style={{ color: 'var(--pb-body-color)' }}
              >
                {renderRichText(stat.label)}
              </dt>
              <dd
                className="order-1 text-5xl"
                style={{
                  ...DISPLAY_STYLE,
                  color: 'var(--pb-heading-color)',
                }}
              >
                {renderRichText(stat.value)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}
