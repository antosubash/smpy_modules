/** Site footer for the layout's footer slot: dark block with logo + nav.
 *
 * The "supported and funded by" partner strip that sits under it on the GCA
 * site is the existing LogoCloud widget — the footer slot takes a list of
 * blocks, so the strip is composed in rather than duplicated here.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { createImageField, mediaLibraryAdapter } from '../../fields';
import { keys, translate, useT } from '../../utils/i18n';

export interface SiteFooterLink {
  label: string;
  href: string;
}

export interface SiteFooterWidgetProps {
  logoUrl: string;
  logoAlt: string;
  homeHref: string;
  links: SiteFooterLink[];
  note: string;
}

export function SiteFooterRender({
  logoUrl,
  logoAlt,
  homeHref,
  links,
  note,
}: SiteFooterWidgetProps) {
  const { t } = useT();
  return (
    <div className="gca-display bg-primary-800 px-6 py-16 text-white lg:py-20">
      <div className="mx-auto flex max-w-[1440px] flex-col items-center gap-10 lg:gap-16">
        <a
          href={homeHref || '/'}
          aria-label={logoAlt || t(keys.pagebuilder.blocks.site_footer.home)}
        >
          {logoUrl ? (
            <img src={logoUrl} alt={logoAlt} className="h-16 w-auto lg:h-20" />
          ) : (
            <span className="text-lg font-bold uppercase tracking-wide">
              {logoAlt || t(keys.pagebuilder.blocks.site_footer.home)}
            </span>
          )}
        </a>

        {links.length > 0 && (
          <nav
            aria-label={t(keys.pagebuilder.blocks.site_footer.nav_aria)}
            className="flex flex-wrap items-center justify-center gap-x-8 gap-y-3"
          >
            {links.map((link, index) => (
              <a
                // biome-ignore lint/suspicious/noArrayIndexKey: author rows are not uniquely identified until filled in
                key={index}
                href={link.href || '#'}
                // The hover tint is a design-pack detail, not the brand action
                // colour — it has to read against the dark block, which the
                // configured brand colour is not guaranteed to do.
                className="text-[18px] font-semibold text-white/90 transition-colors hover:text-[color:var(--pb-footer-link-hover,#ffffff)]"
              >
                {link.label}
              </a>
            ))}
          </nav>
        )}

        {note && <p className="max-w-3xl text-center text-sm text-white/70">{note}</p>}
      </div>
    </div>
  );
}

export const SiteFooterWidget: ComponentConfig<SiteFooterWidgetProps> = {
  label: keys.pagebuilder.blocks.site_footer.label,
  fields: {
    logoUrl: createImageField(mediaLibraryAdapter, keys.pagebuilder.blocks.site_footer.logo_url),
    logoAlt: { type: 'text', label: keys.pagebuilder.blocks.common.logo_alt },
    homeHref: { type: 'text', label: keys.pagebuilder.blocks.site_footer.home_href },
    links: {
      type: 'array',
      label: keys.pagebuilder.blocks.site_footer.links,
      arrayFields: {
        label: { type: 'text', label: keys.pagebuilder.blocks.site_footer.links_label },
        href: { type: 'text', label: keys.pagebuilder.blocks.site_footer.links_href },
      },
      defaultItemProps: { label: 'Link', href: '#' },
      // `translate` rather than a hook: Puck calls this while rendering the
      // array field, outside any component of ours.
      getItemSummary: (item) =>
        item.label || translate(keys.pagebuilder.blocks.site_footer.links_summary),
      max: 12,
    },
    note: { type: 'textarea', label: keys.pagebuilder.blocks.site_footer.note },
  },
  defaultProps: {
    logoUrl: '',
    logoAlt: 'Home',
    homeHref: '/',
    links: [{ label: 'Contact us', href: '#' }],
    note: '',
  },
  render: SiteFooterRender,
};
