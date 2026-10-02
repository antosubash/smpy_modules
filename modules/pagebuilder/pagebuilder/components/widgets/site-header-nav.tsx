/** Desktop and mobile navigation for the SiteHeader widget. */

import { ChevronDown } from 'lucide-react';

import { keys, useT } from '../../utils/i18n';

export interface SiteNavChild {
  label: string;
  href: string;
}

export interface SiteNavItem extends SiteNavChild {
  /**
   * Sub-links. A non-empty list turns the entry into a dropdown and its own
   * `href` becomes decorative — Puck's array editor has no "either/or" field,
   * so the shape carries both and the render picks.
   */
  children?: SiteNavChild[];
}

export function isNavGroup(item: SiteNavItem): boolean {
  return (item.children?.length ?? 0) > 0;
}

const LINK_CLASS =
  'text-[length:var(--pb-nav-link-size,1.125rem)] font-semibold text-primary-800 underline-offset-[10px] hover:underline';

function Dropdown({ item }: { item: SiteNavItem }) {
  return (
    <div className="group relative">
      {/* A group entry is a disclosure, not a destination: rendering it as a
          button keeps the dropdown reachable by keyboard without advertising a
          link that goes nowhere. */}
      <button
        type="button"
        aria-haspopup="true"
        className={`flex items-center gap-1 ${LINK_CLASS}`}
      >
        {item.label}
        <ChevronDown className="size-4 transition-transform group-focus-within:rotate-180 group-hover:rotate-180" />
      </button>
      {/* Opens on hover AND on keyboard focus, so the child links stay
          reachable without a pointer. */}
      <div className="invisible absolute left-0 top-full z-50 min-w-56 pt-3 opacity-0 transition-all group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100">
        <ul className="overflow-hidden rounded-lg bg-[var(--pb-surface,#fff)] py-2 shadow-lg ring-1 ring-black/5">
          {item.children?.map((child) => (
            <li key={child.href || child.label}>
              <a
                href={child.href || '#'}
                // Blur on click: a click-focused link would otherwise hold
                // :focus-within and pin the panel open over the destination.
                onClick={(e) => e.currentTarget.blur()}
                className="block px-5 py-2.5 text-base text-primary-800 transition-colors hover:bg-[var(--pb-surface-muted,#f3f3f4)]"
              >
                {child.label}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function DesktopNav({ items }: { items: SiteNavItem[] }) {
  const { t } = useT();
  return (
    <nav
      aria-label={t(keys.pagebuilder.blocks.site_header.nav_aria)}
      className="hidden items-center gap-8 lg:flex"
    >
      {items.map((item, index) =>
        isNavGroup(item) ? (
          // Index keys: nav entries are author-ordered and an author may well
          // create two blank rows before filling them in, so neither the label
          // nor the href is unique while the row is being typed.
          // biome-ignore lint/suspicious/noArrayIndexKey: author rows are not uniquely identified until filled in
          <Dropdown key={index} item={item} />
        ) : (
          // biome-ignore lint/suspicious/noArrayIndexKey: author rows are not uniquely identified until filled in
          <a key={index} href={item.href || '#'} className={LINK_CLASS}>
            {item.label}
          </a>
        ),
      )}
    </nav>
  );
}

export function MobileNav({
  id,
  items,
  ctaLabel,
  ctaHref,
  onNavigate,
}: {
  id: string;
  items: SiteNavItem[];
  ctaLabel: string;
  ctaHref: string;
  onNavigate: () => void;
}) {
  const { t } = useT();
  return (
    <nav
      id={id}
      aria-label={t(keys.pagebuilder.blocks.site_header.nav_aria)}
      className="border-b border-[color:var(--border,#e4e6e7)] bg-[var(--pb-surface,#fff)] lg:hidden"
    >
      <ul className="mx-auto max-w-[1440px] divide-y divide-[color:var(--border,#e4e6e7)] px-4 sm:px-6">
        {items.map((item, index) =>
          isNavGroup(item) ? (
            // biome-ignore lint/suspicious/noArrayIndexKey: author rows are not uniquely identified until filled in
            <li key={index} className="py-3">
              <p className="px-1 py-1 text-[13px] font-semibold uppercase tracking-wide text-primary-800 opacity-80">
                {item.label}
              </p>
              <ul className="mt-1">
                {item.children?.map((child, childIndex) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: author rows are not uniquely identified until filled in
                  <li key={childIndex}>
                    <a
                      href={child.href || '#'}
                      onClick={onNavigate}
                      className="block rounded-md px-3 py-2.5 text-[15px] text-primary-800 transition-colors hover:bg-[var(--pb-surface-muted,#f3f3f4)]"
                    >
                      {child.label}
                    </a>
                  </li>
                ))}
              </ul>
            </li>
          ) : (
            // biome-ignore lint/suspicious/noArrayIndexKey: author rows are not uniquely identified until filled in
            <li key={index} className="py-1">
              <a
                href={item.href || '#'}
                onClick={onNavigate}
                className="block rounded-md px-3 py-3 text-[15px] font-medium text-primary-800 transition-colors hover:bg-[var(--pb-surface-muted,#f3f3f4)]"
              >
                {item.label}
              </a>
            </li>
          ),
        )}
        {ctaLabel && (
          <li className="py-4">
            <a
              href={ctaHref || '#'}
              onClick={onNavigate}
              className="block rounded-[var(--pb-button-radius,9999px)] bg-primary-800 px-6 py-3 text-center text-[15px] font-semibold text-white transition-colors hover:bg-primary-900"
            >
              {ctaLabel}
            </a>
          </li>
        )}
      </ul>
    </nav>
  );
}
