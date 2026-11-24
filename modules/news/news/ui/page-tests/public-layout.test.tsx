// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';

vi.mock('@inertiajs/react', () => ({
  usePage: () => ({
    props: {
      locale: 'en',
      auth: { isAuthenticated: false },
      i18n: { locale: 'en', supportedLocales: ['en'] },
    },
    url: '/news/story',
  }),
  Head: () => null,
  Link: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock('@simple-module-py/ui/components/BrandingHead', () => ({ BrandingHead: () => null }));
(globalThis as { React?: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const { default: PublicArticle } = await import('../../pages/PublicArticle');
const { default: PublicIndex } = await import('../../pages/PublicIndex');
// This is the host's optional entry, which must install the frame renderer.
await import('../../pagebuilder-blocks');

const frame = {
  layout_header: {
    content: [
      { type: 'Heading', props: { id: 'h', text: 'Site header' } },
      {
        type: 'SiteHeader',
        props: {
          id: 'nav',
          logoUrl: '',
          logoAlt: 'Brand',
          homeHref: '/',
          utilityLinks: [],
          navItems: [],
          ctaLabel: '',
          ctaHref: '',
          showLocaleSwitcher: false,
          sticky: true,
        },
      },
    ],
  },
  layout_footer: {
    content: [
      { type: 'Heading', props: { id: 'f', text: 'Site footer' } },
      {
        type: 'SiteFooter',
        props: {
          id: 'footer-nav',
          logoUrl: '',
          logoAlt: 'Brand',
          homeHref: '/',
          links: [],
          note: '',
        },
      },
    ],
  },
  site_nav: {
    header: [{ label: 'About', href: '/p/about' }],
    footer: [{ label: 'Imprint', href: '/p/imprint' }],
  },
};
const article = { title: 'Story', data: { content: [] }, meta_description: null, og_image: null };
const preview = {
  status: 'draft' as const,
  has_unpublished_changes: false,
  live_url: null,
  editor_url: '/admin/news/articles/1/edit',
};
const archive = {
  heading: 'News',
  items: [],
  page: 1,
  pages: 1,
  total: 0,
  base_path: '/news/',
  feed_url: '/news/feed.xml',
};

it.each(['article', 'index', 'preview'])(
  'renders the site frame around the public %s only with layout props',
  async (page) => {
    const container = document.createElement('div');
    const root = createRoot(container);
    const draw = (withFrame: boolean) =>
      page === 'index' ? (
        <PublicIndex {...archive} {...(withFrame ? frame : {})} />
      ) : (
        <PublicArticle
          {...article}
          {...(withFrame ? frame : {})}
          preview={page === 'preview' ? preview : undefined}
        />
      );
    try {
      await act(async () => root.render(draw(false)));
      const plain = container.innerHTML;
      expect(container.querySelector('main')).toBeNull();
      await act(async () => root.render(draw(true)));
      await vi.waitFor(
        async () => {
          await act(async () => {});
          expect(container.querySelector('[data-testid="site-header"]')?.textContent).toContain(
            'Site header',
          );
        },
        { timeout: 3000 },
      );
      expect(container.querySelector('[data-testid="site-footer"]')?.textContent).toContain(
        'Site footer',
      );
      expect(
        container.querySelector('[data-testid="site-header"] a[href="/p/about"]')?.textContent,
      ).toBe('About');
      expect(
        container.querySelector('[data-testid="site-footer"] a[href="/p/imprint"]')?.textContent,
      ).toBe('Imprint');
      expect(container.querySelector('main h1')?.textContent).toBe(
        page === 'index' ? 'News' : 'Story',
      );
      if (page === 'preview') {
        const banner = container.querySelector('aside[aria-label="Preview"]');
        expect(banner?.textContent).toContain('Draft');
        // Above the frame so a sticky site header cannot hide the warning.
        expect(banner?.nextElementSibling).toBe(container.querySelector('.pb-public'));
      }
      await act(async () => root.render(draw(false)));
      expect(container.innerHTML).toBe(plain);
    } finally {
      await act(async () => root.unmount());
    }
  },
);
