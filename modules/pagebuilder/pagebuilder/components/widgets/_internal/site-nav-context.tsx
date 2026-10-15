import { createContext, type ReactNode, useContext } from 'react';

/** A page that asked to be in the site's nav, as `pagebuilder.site_nav` resolved it. */
export interface SiteNavPage {
  label: string;
  href: string;
}

export interface SiteNav {
  header: SiteNavPage[];
  footer: SiteNavPage[];
}

const EMPTY: SiteNav = { header: [], footer: [] };

// Empty by default: the layout editor renders the same widgets without a
// provider, and there the header must show only what the author put in it.
const SiteNavContext = createContext<SiteNav>(EMPTY);

export function SiteNavProvider({ nav, children }: { nav?: SiteNav | null; children: ReactNode }) {
  return <SiteNavContext.Provider value={nav ?? EMPTY}>{children}</SiteNavContext.Provider>;
}

export function useSiteNavPages(slot: keyof SiteNav): SiteNavPage[] {
  return useContext(SiteNavContext)[slot] ?? [];
}

/**
 * The layout's own links, then every flagged page the layout doesn't already
 * link to. `linked` is every href the layout carries, dropdown children
 * included: a page the author placed by hand keeps that position instead of
 * appearing a second time at the end.
 */
export function appendPages<T>(
  links: T[],
  linked: Iterable<string>,
  pages: SiteNavPage[],
  toLink: (page: SiteNavPage) => T,
): T[] {
  const seen = new Set(linked);
  const extra = pages.filter((page) => !seen.has(page.href)).map(toLink);
  return extra.length > 0 ? [...links, ...extra] : links;
}
