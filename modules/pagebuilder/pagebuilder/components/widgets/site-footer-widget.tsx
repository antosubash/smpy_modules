/** Site footer for the layout's footer slot: dark block with logo + nav.
 *
 * The "supported and funded by" partner strip that sits under it on the GCA
 * site is the existing LogoCloud widget — the footer slot takes a list of
 * blocks, so the strip is composed in rather than duplicated here.
 */

import type { ComponentConfig } from '@measured/puck';

import { createImageField, mediaLibraryAdapter } from '../../fields';

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
  return (
    <div className="gca-display bg-primary-800 px-6 py-16 text-white lg:py-20">
      <div className="mx-auto flex max-w-[1440px] flex-col items-center gap-10 lg:gap-16">
        <a href={homeHref || '/'} aria-label={logoAlt || 'Home'}>
          {logoUrl ? (
            <img src={logoUrl} alt={logoAlt} className="h-16 w-auto lg:h-20" />
          ) : (
            <span className="text-lg font-bold uppercase tracking-wide">{logoAlt || 'Home'}</span>
          )}
        </a>

        {links.length > 0 && (
          <nav
            aria-label="Footer"
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
  label: 'Site footer (logo + links)',
  fields: {
    logoUrl: createImageField(mediaLibraryAdapter, 'Logo (reversed / light)'),
    logoAlt: { type: 'text', label: 'Logo alt text' },
    homeHref: { type: 'text', label: 'Logo link' },
    links: {
      type: 'array',
      label: 'Links',
      arrayFields: {
        label: { type: 'text', label: 'Label' },
        href: { type: 'text', label: 'Link' },
      },
      defaultItemProps: { label: 'Link', href: '#' },
      getItemSummary: (item) => item.label || 'Link',
      max: 12,
    },
    note: { type: 'textarea', label: 'Small print (optional)' },
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
