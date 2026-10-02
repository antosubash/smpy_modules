/** FeatureCards render. Icon map, types and style tables live in
 *  feature-cards-styles.ts so this file stays under the 300-line cap. */

/** FeatureCardsWidget types, helpers and render — split from feature-cards-widget.tsx,
 *  which keeps the field definitions, so both stay under the 300-line cap. */

import { ArrowRight, ArrowUpRight } from 'lucide-react';
import type { CSSProperties } from 'react';
import { keys, useT } from '../../utils/i18n';
import { cn } from '../../utils/widgetUtils';
import { AccentText } from './_internal/accent-text';
import { RichTextBlock, renderRichText } from './_internal/rich-text';
import {
  ChartAreaSolid,
  MagnifyingGlassChartSolid,
  PawSolid,
  type SolidIconProps,
  TemperatureSolid,
  TreeSolid,
  WaterSolid,
} from './_internal/solid-icons';
import { TextLink } from './_shared/text-link';

// Named glyphs selectable per card — solid icons matching the GCA design
// system "Icons" page (SNAG_009/SNAG_014). Keep the set small and meaningful;
// unknown names fall back to a plain coloured badge.

export type { FeatureCardItem, FeatureCardsWidgetProps } from './feature-cards-styles';

import {
  CARD_BODY_STYLE,
  CARD_TAG_STYLE,
  CARD_TITLE_STYLE,
  COLS_CLASS,
  DISPLAY_STYLE,
  EYEBROW_STYLE,
  type FeatureCardsWidgetProps,
  HEADING_LG_STYLE,
  ICON_MAP,
} from './feature-cards-styles';

export const FeatureCardsWidgetRender = ({
  eyebrow,
  title,
  subtitle,
  linkLabel,
  linkHref,
  cardLinkLabel,
  surface = 'default',
  cardSurface = 'default',
  columns,
  items,
}: FeatureCardsWidgetProps) => {
  const { t } = useT();
  const cardLink = cardLinkLabel ?? t(keys.pagebuilder.blocks.feature_cards.card_link_default);
  const hasHeaderLink = Boolean(linkLabel && linkHref);
  const hasSide = Boolean(eyebrow) || hasHeaderLink;
  const panelClass =
    surface === 'muted' ? 'rounded-3xl bg-[#f3f3f4] px-6 py-12 sm:px-10 lg:px-12' : '';
  const cardClass =
    cardSurface === 'muted'
      ? 'group flex flex-col rounded-xl bg-[#f3f3f4] p-6 transition-shadow hover:shadow-md'
      : 'group flex flex-col rounded-xl border border-[var(--border,#e4e6e7)] bg-white p-6 transition-shadow hover:shadow-lg dark:bg-gray-900';
  const headerLink = hasHeaderLink ? <TextLink label={linkLabel} href={linkHref} /> : null;

  return (
    <section className="container mx-auto px-4 py-16 sm:px-6 lg:px-8">
      <div className={panelClass}>
        {(title || subtitle || hasSide) &&
          (hasSide ? (
            <div className="mb-10 grid items-center gap-4 sm:grid-cols-[1fr_auto_1fr]">
              <span className="font-medium" style={EYEBROW_STYLE}>
                {renderRichText(eyebrow)}
              </span>
              <div className="mx-auto max-w-3xl text-center">
                {title && (
                  <h2 className="leading-[var(--pb-heading-leading,1.1)]" style={HEADING_LG_STYLE}>
                    {renderRichText(title)}
                  </h2>
                )}
                {subtitle && (
                  <RichTextBlock
                    text={subtitle}
                    className="mt-3 text-lg"
                    style={{ color: 'var(--pb-body-color)' }}
                  />
                )}
              </div>
              <div className="sm:justify-self-end">{headerLink}</div>
            </div>
          ) : (
            <div className="text-center mb-10 max-w-3xl mx-auto">
              {title && (
                <h2 className="text-3xl sm:text-4xl lg:text-5xl" style={DISPLAY_STYLE}>
                  {renderRichText(title)}
                </h2>
              )}
              {subtitle && (
                <RichTextBlock
                  text={subtitle}
                  className="mt-3 text-lg"
                  style={{ color: 'var(--pb-body-color)' }}
                />
              )}
            </div>
          ))}
        {items && items.length > 0 ? (
          <div className={cn('grid gap-6 grid-cols-1', COLS_CLASS[columns])}>
            {items.map((item, idx) => {
              const Icon = item.icon ? ICON_MAP[item.icon] : undefined;
              const linked = Boolean(item.href);
              const colored = Boolean(item.cardBg);
              return (
                <a
                  // biome-ignore lint/suspicious/noArrayIndexKey: author-ordered array with no stable id; card content repeats, so a content key collides
                  key={idx}
                  href={item.href || '#'}
                  className={
                    colored
                      ? 'group flex min-h-[var(--pb-card-min-h,0)] flex-col rounded-xl p-6 transition-shadow hover:shadow-lg'
                      : cardClass
                  }
                  style={colored ? { backgroundColor: item.cardBg } : undefined}
                >
                  <div className="mb-4 flex items-start justify-between gap-2">
                    {item.iconUrl ? (
                      <img
                        src={item.iconUrl}
                        alt={item.iconAlt || ''}
                        loading="lazy"
                        className={
                          colored
                            ? 'h-36 w-auto max-w-[70%] object-contain object-left'
                            : 'size-12 object-contain'
                        }
                      />
                    ) : (
                      <div
                        className="flex size-12 items-center justify-center rounded-lg"
                        style={{
                          backgroundColor:
                            item.iconBg || (Icon ? 'var(--pb-accent)' : 'var(--pb-surface-muted)'),
                        }}
                      >
                        {Icon && <Icon className="size-6 text-white" />}
                      </div>
                    )}
                    {/* On colored cards the tag is a bold lead-in line above the
											    description (BioGarden's "Jetzt anmelden"), so it is
											    rendered down there rather than as a pill up here. */}
                    {item.tag && !colored && (
                      <span
                        className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium"
                        style={{
                          backgroundColor: 'var(--pb-surface-muted)',
                          color: 'var(--pb-heading-color)',
                        }}
                      >
                        {renderRichText(item.tag, { allowLinks: false })}
                      </span>
                    )}
                  </div>
                  <h3
                    className="transition-colors"
                    style={
                      colored
                        ? {
                            ...CARD_TITLE_STYLE,
                            color: 'var(--pb-surface-contrast, #ffffff)',
                          }
                        : CARD_TITLE_STYLE
                    }
                  >
                    {renderRichText(item.title, { allowLinks: false })}
                  </h3>
                  {/* Colored cards put the tag, description and arrow button in
										    one bottom group — tag as a bold lead-in, copy on the left
										    (~2/3 of the card), circle bottom-right — as the BioGarden
										    Figma does. `mt-auto` sits on the GROUP, not on either
										    child: on the tag it would break tagless cards, on the row
										    it would push the copy away from the tag leading into it. */}
                  {colored ? (
                    <div className="mt-auto">
                      {item.tag && (
                        <p
                          className="pt-6 font-bold"
                          style={{
                            ...CARD_TAG_STYLE,
                            color: 'var(--pb-surface-contrast, #ffffff)',
                          }}
                        >
                          {renderRichText(item.tag, { allowLinks: false })}
                        </p>
                      )}
                      <div className="flex items-end justify-between gap-4">
                        {item.description && (
                          <p
                            className="mt-2 max-w-[66%] leading-relaxed"
                            style={{
                              ...CARD_BODY_STYLE,
                              color: 'var(--pb-surface-contrast, #ffffff)',
                              opacity: 0.85,
                            }}
                          >
                            {/* `*word*` marks the semibold key phrase the
															    Figma uses to lead each description. Links off:
															    this sits inside the card-wide <a>. */}
                            <AccentText text={item.description} allowLinks={false} />
                          </p>
                        )}
                        {linked && (
                          // The wrapping <a> already names the link (card
                          // title), so the arrow is decorative.
                          <span
                            className="flex size-16 shrink-0 items-center justify-center rounded-full bg-[var(--pb-surface,#ffffff)]"
                            style={{
                              color: 'var(--pb-heading-color, #161728)',
                            }}
                          >
                            <ArrowRight className="size-6" />
                          </span>
                        )}
                      </div>
                    </div>
                  ) : (
                    item.description && (
                      <p className="mt-2 leading-relaxed" style={CARD_BODY_STYLE}>
                        {/* Inline (not RichTextBlock): the whole card is one
													    <a>, so a `[label](href)` here would nest anchors. */}
                        {renderRichText(item.description, {
                          allowLinks: false,
                        })}
                      </p>
                    )
                  )}
                  {linked &&
                    (colored ? null : (
                      <span className="mt-auto inline-flex items-center gap-1 pt-6 text-sm font-medium text-[color:var(--pb-link-color,var(--pb-accent))] group-hover:text-[color:var(--pb-link-hover-color,var(--pb-link-color,var(--pb-accent)))]">
                        {renderRichText(cardLink, { allowLinks: false })}
                        <ArrowUpRight className="size-4" />
                      </span>
                    ))}
                </a>
              );
            })}
          </div>
        ) : (
          <EmptyState />
        )}
      </div>
    </section>
  );
};

function EmptyState() {
  const { t } = useT();
  return (
    <div className="text-center text-gray-500 py-6">
      {t(keys.pagebuilder.blocks.feature_cards.empty)}
    </div>
  );
}
