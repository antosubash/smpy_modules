/** Site header for the layout's header slot: utility bar + primary nav bar. */

import type { ComponentConfig } from '@puckeditor/core';
import { Menu, X } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';

import { createCheckboxField, createImageField, mediaLibraryAdapter } from '../../fields';
import { keys, translate, useT } from '../../utils/i18n';
import { appendPages, useSiteNavPages } from './_internal/site-nav-context';
import { SOCIAL_ICON_OPTIONS, SocialIcon, type SocialIconName } from './_shared';
import { HeaderLocaleSwitcher, resolveCta, useIsSignedIn } from './site-header-account';
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
  /** Shown instead of the CTA once the visitor is signed in; empty keeps the CTA. */
  signedInLabel?: string;
  signedInHref?: string;
  showLocaleSwitcher: boolean;
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
  navItems: layoutNavItems,
  ctaLabel: anonymousCtaLabel,
  ctaHref: anonymousCtaHref,
  signedInLabel,
  signedInHref,
  showLocaleSwitcher,
  sticky,
}: SiteHeaderWidgetProps) {
  const { t } = useT();
  // Pages flagged "show in header nav" follow the layout's own entries.
  const navItems = appendPages(
    layoutNavItems,
    layoutNavItems.flatMap((item) => [item.href, ...(item.children ?? []).map((c) => c.href)]),
    useSiteNavPages('header'),
    (page): SiteNavItem => ({ ...page, children: [] }),
  );
  const signedIn = useIsSignedIn();
  const { label: ctaLabel, href: ctaHref } = resolveCta(
    signedIn,
    { label: anonymousCtaLabel, href: anonymousCtaHref },
    { label: signedInLabel, href: signedInHref },
  );
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const mobileMenuId = useId();

  useEffect(() => {
    if (!mobileOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setMobileOpen(false);
      menuButtonRef.current?.focus();
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [mobileOpen]);

  return (
    // The public page wraps this slot in its own <header>, which is exactly as
    // tall as this block — so `position: sticky` here would have nothing to
    // travel within. The attribute lets widgets-base.css make that *wrapper*
    // sticky instead; see the `:has()` rule there.
    <div data-pb-site-header={sticky ? 'sticky' : 'static'} className="gca-display">
      <UtilityBar links={utilityLinks} />

      <div className="border-b border-[color:var(--border,#e4e6e7)] bg-[var(--pb-surface,#fff)]">
        <div className="mx-auto flex min-h-[72px] max-w-[1440px] items-center justify-between px-4 sm:px-6 lg:min-h-[112px] lg:px-12 lg:py-4">
          <a
            href={homeHref || '/'}
            aria-label={logoAlt || t(keys.pagebuilder.blocks.site_header.home)}
            className="shrink-0"
          >
            {logoUrl ? (
              <img src={logoUrl} alt={logoAlt} className="h-10 w-auto lg:h-16" />
            ) : (
              <span className="text-sm font-bold uppercase leading-tight tracking-wide text-primary-800">
                {logoAlt || t(keys.pagebuilder.blocks.site_header.home)}
              </span>
            )}
          </a>

          <DesktopNav items={navItems} />

          {/* One group, so the row keeps three items (logo, nav, actions) and
              `justify-between` cannot float the switcher between nav and CTA. */}
          <div data-pb-header-actions className="flex shrink-0 items-center gap-3">
            <HeaderLocaleSwitcher show={showLocaleSwitcher} />

            {ctaLabel && (
              <a
                href={ctaHref || '#'}
                className="hidden shrink-0 whitespace-nowrap rounded-[var(--pb-button-radius,9999px)] bg-primary-800 px-6 py-2.5 text-[17px] font-semibold text-white transition-colors hover:bg-primary-900 lg:inline-block"
              >
                {ctaLabel}
              </a>
            )}

            <button
              ref={menuButtonRef}
              type="button"
              onClick={() => setMobileOpen((open) => !open)}
              aria-label={
                mobileOpen
                  ? t(keys.pagebuilder.blocks.site_header.close_menu)
                  : t(keys.pagebuilder.blocks.site_header.open_menu)
              }
              aria-expanded={mobileOpen}
              aria-controls={mobileMenuId}
              className="-mr-2 inline-flex size-11 items-center justify-center rounded-md text-primary-800 transition-colors hover:text-primary-900 lg:hidden"
            >
              {mobileOpen ? <X className="size-6" /> : <Menu className="size-6" />}
            </button>
          </div>
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
  label: keys.pagebuilder.blocks.site_header.label,
  fields: {
    logoUrl: createImageField(mediaLibraryAdapter, keys.pagebuilder.blocks.site_header.logo_url),
    logoAlt: { type: 'text', label: keys.pagebuilder.blocks.common.logo_alt },
    homeHref: { type: 'text', label: keys.pagebuilder.blocks.site_header.home_href },
    utilityLinks: {
      type: 'array',
      label: keys.pagebuilder.blocks.site_header.utility_links,
      arrayFields: {
        label: { type: 'text', label: keys.pagebuilder.blocks.site_header.utility_links_label },
        href: { type: 'text', label: keys.pagebuilder.blocks.site_header.utility_links_href },
        icon: {
          type: 'select',
          label: keys.pagebuilder.blocks.site_header.utility_links_icon,
          options: [
            { label: keys.pagebuilder.blocks.site_header.utility_links_icon_blank, value: '' },
            ...SOCIAL_ICON_OPTIONS,
          ],
        },
      },
      defaultItemProps: { label: 'Link', href: '#', icon: '' },
      // `translate` rather than a hook: Puck calls this while rendering the
      // array field, outside any component of ours.
      getItemSummary: (item) =>
        item.label || translate(keys.pagebuilder.blocks.site_header.utility_links_summary),
      max: 8,
    },
    navItems: {
      type: 'array',
      label: keys.pagebuilder.blocks.site_header.nav_items,
      arrayFields: {
        label: { type: 'text', label: keys.pagebuilder.blocks.site_header.nav_items_label },
        href: { type: 'text', label: keys.pagebuilder.blocks.site_header.nav_items_href },
        children: {
          type: 'array',
          label: keys.pagebuilder.blocks.site_header.nav_items_children,
          arrayFields: {
            label: {
              type: 'text',
              label: keys.pagebuilder.blocks.site_header.nav_items_children_label,
            },
            href: {
              type: 'text',
              label: keys.pagebuilder.blocks.site_header.nav_items_children_href,
            },
          },
          defaultItemProps: { label: 'Sub-link', href: '#' },
          getItemSummary: (child) =>
            child.label ||
            translate(keys.pagebuilder.blocks.site_header.nav_items_children_summary),
          max: 10,
        },
      },
      defaultItemProps: { label: 'Section', href: '#', children: [] },
      getItemSummary: (item) =>
        item.label || translate(keys.pagebuilder.blocks.site_header.nav_items_summary),
      max: 10,
    },
    ctaLabel: { type: 'text', label: keys.pagebuilder.blocks.site_header.cta_label },
    ctaHref: { type: 'text', label: keys.pagebuilder.blocks.site_header.cta_href },
    signedInLabel: { type: 'text', label: keys.pagebuilder.blocks.site_header.signed_in_label },
    signedInHref: { type: 'text', label: keys.pagebuilder.blocks.site_header.signed_in_href },
    showLocaleSwitcher: createCheckboxField(
      keys.pagebuilder.blocks.site_header.show_locale_switcher,
    ),
    sticky: createCheckboxField(keys.pagebuilder.blocks.site_header.sticky),
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
    signedInLabel: '',
    signedInHref: '',
    showLocaleSwitcher: false,
    sticky: true,
  },
  render: SiteHeaderRender,
};
