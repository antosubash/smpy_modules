/** Site header for the layout's header slot: utility bar + primary nav bar. */

import type { ComponentConfig } from '@measured/puck';
import { Menu, X } from 'lucide-react';
import { useId, useState } from 'react';

import { createCheckboxField, createImageField, mediaLibraryAdapter } from '../../fields';
import { SOCIAL_ICON_OPTIONS, SocialIcon, type SocialIconName } from './_shared';
import { DesktopNav, MobileNav, type SiteNavItem } from './site-header-nav';

export interface UtilityLink {
  label: string;
  href: string;
  /** Empty renders the label as text; otherwise the icon replaces it. */
  icon?: SocialIconName | '';
}

export interface SiteHeaderWidgetProps {
  logoUrl: string;
  logoAlt: string;
  homeHref: string;
  utilityLinks: UtilityLink[];
  navItems: SiteNavItem[];
  ctaLabel: string;
  ctaHref: string;
  sticky: boolean;
}

function UtilityBar({ links }: { links: UtilityLink[] }) {
  if (links.length === 0) return null;
  return (
    <div className="bg-primary-800 text-white">
      <div className="mx-auto flex h-10 max-w-[1440px] items-center justify-end gap-4 px-4 text-[13px] sm:gap-6 sm:px-6 lg:px-12">
        {links.map((link, index) => (
          <a
            // biome-ignore lint/suspicious/noArrayIndexKey: author rows are not uniquely identified until filled in
            key={index}
            href={link.href || '#'}
            aria-label={link.icon ? link.label : undefined}
            className="opacity-90 transition-opacity hover:opacity-100"
          >
            {link.icon ? <SocialIcon name={link.icon} className="size-4" /> : link.label}
          </a>
        ))}
      </div>
    </div>
  );
}

export function SiteHeaderRender({
  logoUrl,
  logoAlt,
  homeHref,
  utilityLinks,
  navItems,
  ctaLabel,
  ctaHref,
  sticky,
}: SiteHeaderWidgetProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const mobileMenuId = useId();

  return (
    // The public page wraps this slot in its own <header>, which is exactly as
    // tall as this block — so `position: sticky` here would have nothing to
    // travel within. The attribute lets widgets-base.css make that *wrapper*
    // sticky instead; see the `:has()` rule there.
    <div data-pb-site-header={sticky ? 'sticky' : 'static'} className="gca-display">
      <UtilityBar links={utilityLinks} />

      <div className="border-b border-[color:var(--border,#e4e6e7)] bg-[var(--pb-surface,#fff)]">
        <div className="mx-auto flex h-[72px] max-w-[1440px] items-center justify-between px-4 sm:px-6 lg:h-[112px] lg:px-12">
          <a href={homeHref || '/'} aria-label={logoAlt || 'Home'}>
            {logoUrl ? (
              <img src={logoUrl} alt={logoAlt} className="h-10 w-auto lg:h-16" />
            ) : (
              <span className="text-sm font-bold uppercase leading-tight tracking-wide text-primary-800">
                {logoAlt || 'Home'}
              </span>
            )}
          </a>

          <DesktopNav items={navItems} />

          {ctaLabel && (
            <a
              href={ctaHref || '#'}
              className="hidden rounded-[var(--pb-button-radius,9999px)] bg-primary-800 px-6 py-2.5 text-[17px] font-semibold text-white transition-colors hover:bg-primary-900 lg:inline-block"
            >
              {ctaLabel}
            </a>
          )}

          <button
            type="button"
            onClick={() => setMobileOpen((open) => !open)}
            aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={mobileOpen}
            aria-controls={mobileMenuId}
            className="-mr-2 inline-flex size-10 items-center justify-center rounded-md text-primary-800 transition-colors hover:text-primary-900 lg:hidden"
          >
            {mobileOpen ? <X className="size-6" /> : <Menu className="size-6" />}
          </button>
        </div>
      </div>

      {mobileOpen && (
        <MobileNav
          id={mobileMenuId}
          items={navItems}
          ctaLabel={ctaLabel}
          ctaHref={ctaHref}
          onNavigate={() => setMobileOpen(false)}
        />
      )}
    </div>
  );
}

export const SiteHeaderWidget: ComponentConfig<SiteHeaderWidgetProps> = {
  label: 'Site header (logo + navigation)',
  fields: {
    logoUrl: createImageField(mediaLibraryAdapter, 'Logo'),
    logoAlt: { type: 'text', label: 'Logo alt text' },
    homeHref: { type: 'text', label: 'Logo link' },
    utilityLinks: {
      type: 'array',
      label: 'Utility bar (top strip)',
      arrayFields: {
        label: { type: 'text', label: 'Label' },
        href: { type: 'text', label: 'Link' },
        icon: {
          type: 'select',
          label: 'Show as icon (optional)',
          options: [{ label: 'Text label', value: '' }, ...SOCIAL_ICON_OPTIONS],
        },
      },
      defaultItemProps: { label: 'Link', href: '#', icon: '' },
      getItemSummary: (item) => item.label || 'Link',
      max: 8,
    },
    navItems: {
      type: 'array',
      label: 'Navigation',
      arrayFields: {
        label: { type: 'text', label: 'Label' },
        href: { type: 'text', label: 'Link (ignored when sub-links are set)' },
        children: {
          type: 'array',
          label: 'Sub-links (makes this a dropdown)',
          arrayFields: {
            label: { type: 'text', label: 'Label' },
            href: { type: 'text', label: 'Link' },
          },
          defaultItemProps: { label: 'Sub-link', href: '#' },
          getItemSummary: (child) => child.label || 'Sub-link',
          max: 10,
        },
      },
      defaultItemProps: { label: 'Section', href: '#', children: [] },
      getItemSummary: (item) => item.label || 'Section',
      max: 10,
    },
    ctaLabel: { type: 'text', label: 'Call-to-action label' },
    ctaHref: { type: 'text', label: 'Call-to-action link' },
    sticky: createCheckboxField('Stick to the top of the page on scroll'),
  },
  defaultProps: {
    logoUrl: '',
    logoAlt: 'Home',
    homeHref: '/',
    utilityLinks: [],
    navItems: [
      { label: 'Home', href: '/', children: [] },
      { label: 'Contact', href: '#', children: [] },
    ],
    ctaLabel: '',
    ctaHref: '#',
    sticky: true,
  },
  render: SiteHeaderRender,
};
