// @vitest-environment happy-dom
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@inertiajs/react', () => ({
  usePage: () => ({
    props: { auth: { isAuthenticated: false }, i18n: { locale: 'en', supportedLocales: ['en'] } },
  }),
}));

(globalThis as { React?: unknown }).React = React;

import type { SiteNav } from './_internal/site-nav-context';
import type { SiteFooterWidgetProps } from './site-footer-widget';
import type { SiteHeaderWidgetProps } from './site-header-widget';

const { SiteNavProvider } = await import('./_internal/site-nav-context');
const { SiteHeaderRender, SiteHeaderWidget } = await import('./site-header-widget');
const { SiteFooterRender, SiteFooterWidget } = await import('./site-footer-widget');

const NAV: SiteNav = {
  header: [
    { label: 'About', href: '/p/about' },
    { label: 'Team', href: '/p/team' },
  ],
  footer: [
    { label: 'Imprint', href: '/p/imprint' },
    { label: 'Contact us', href: '/p/contact' },
  ],
};

function header(nav: SiteNav | null, props: Partial<SiteHeaderWidgetProps> = {}): string {
  const all = { ...SiteHeaderWidget.defaultProps, ...props } as SiteHeaderWidgetProps;
  return renderToStaticMarkup(
    <SiteNavProvider nav={nav}>
      <SiteHeaderRender {...all} />
    </SiteNavProvider>,
  );
}

function footer(nav: SiteNav | null, props: Partial<SiteFooterWidgetProps> = {}): string {
  const all = { ...SiteFooterWidget.defaultProps, ...props } as SiteFooterWidgetProps;
  return renderToStaticMarkup(
    <SiteNavProvider nav={nav}>
      <SiteFooterRender {...all} />
    </SiteNavProvider>,
  );
}

const hrefs = (html: string) => [...html.matchAll(/href="([^"]+)"/g)].map((m) => m[1]);

describe('flagged pages in the site header', () => {
  it('follow the layout’s own entries', () => {
    const out = hrefs(header(NAV));
    // Home link (logo), the layout's Home + Contact, then the flagged pages.
    expect(out).toEqual(['/', '/', '#', '/p/about', '/p/team']);
  });

  it('are not repeated when the layout already links them, even in a dropdown', () => {
    const out = header(NAV, {
      navItems: [
        { label: 'Company', href: '#', children: [{ label: 'Our team', href: '/p/team' }] },
      ],
    });
    expect(hrefs(out).filter((href) => href === '/p/team')).toHaveLength(1);
    expect(out).toContain('>About<');
    expect(out).toContain('>Our team<');
    expect(out).not.toContain('>Team<');
  });

  it('are absent without a provider, as in the layout editor', () => {
    expect(header(null)).not.toContain('/p/about');
  });
});

describe('flagged pages in the site footer', () => {
  it('follow the layout’s own links, skipping ones it already has', () => {
    const out = footer(NAV, { links: [{ label: 'Contact us', href: '/p/contact' }] });
    expect(hrefs(out)).toEqual(['/', '/p/contact', '/p/imprint']);
  });

  it('treat a trailing slash in the layout as the same page', () => {
    const out = footer(NAV, { links: [{ label: 'Imprint', href: '/p/imprint/' }] });
    expect(hrefs(out)).toEqual(['/', '/p/imprint/', '/p/contact']);
  });

  it('show even when the layout has no links of its own', () => {
    expect(footer(NAV, { links: [] })).toContain('>Imprint<');
  });
});
