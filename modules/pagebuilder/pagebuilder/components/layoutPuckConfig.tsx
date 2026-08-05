import type { Config } from '@puckeditor/core';

import { registeredBlocks, registryVersion } from './blockRegistry';
import { basePageConfig, getPuckConfig } from './puckConfig';
import { SiteFooterWidget } from './widgets/site-footer-widget';
import { SiteHeaderWidget } from './widgets/site-header-widget';

let cachedConfig: Config | null = null;
let cachedVersion = -1;

/**
 * The site-layout palette.
 *
 * A small, curated set — see `categories` below, which is what the palette is
 * built from. The page-shaped root is replaced with a transparent pass-through
 * so the host wrapper (`<header>`/`<footer>`) controls layout rather than
 * Puck's default page container.
 *
 * A module's blocks only appear here if it registered with `layout: true` — a
 * news feed belongs on a page, not in the site chrome.
 *
 * Memoised on the registry version, not unconditionally: caching on first call
 * would drop any block registered after the first render. Call it inside a
 * component, never at module scope.
 */
export function getLayoutPuckConfig(): Config {
  if (cachedConfig && cachedVersion === registryVersion()) return cachedConfig;

  const pageConfig = getPuckConfig();
  const categories: Record<string, { title?: string; visible?: boolean; components: string[] }> = {
    // Site chrome is registered here and NOT in the page palette: a nav bar
    // dropped into the middle of a page would render a second one under the
    // real header.
    chrome: { title: 'Site chrome', components: ['SiteHeader', 'SiteFooter'] },
    typography: { components: ['Heading', 'Text'] },
    media: { components: ['Image'] },
    actions: { components: ['Button'] },
    // The partner strip under the GCA footer is this widget rather than markup
    // baked into SiteFooter, so an author can reorder or drop it.
    collections: { title: 'Collections', components: ['LogoCloud'] },
    layout: { components: ['Spacer', 'Divider'] },
    // Offered in the site-layout editor before the palette was curated, so a
    // header or footer saved back then may contain one. Kept registered — Puck
    // renders nothing at all for a type its config doesn't know, with no error
    // and no placeholder, so removing them outright would quietly delete
    // sections from live sites — but `visible: false` keeps them out of the
    // palette, so nobody adds a new one.
    _legacy: {
      visible: false,
      components: [
        'PageHeader',
        'Hero',
        'EyebrowSection',
        'MediaObject',
        'CallToAction',
        'FeatureCards',
        'Faq',
        'Stats',
        'ArticleCards',
        'ContactCards',
        'ContactForm',
        'Tags',
      ],
    },
  };

  // Built from the categories above — an allowlist, not "the page palette minus
  // a couple". The subtractive form silently inherited every block added to the
  // page: when the catalogue went from 20 to 56, the header/footer editor
  // quietly started offering Leaderboard, Timeline and ~45 other page sections
  // under Puck's catch-all "Other" group, because they had no category here.
  // Site chrome is a deliberately small palette; it has to stay one by
  // construction — and anything an author could once place here has to stay
  // renderable, which is what `_legacy` above is for.
  const components: Record<string, unknown> = {};
  for (const name of Object.values(categories).flatMap((c) => c.components)) {
    const block = (basePageConfig.components as Record<string, unknown>)[name];
    if (block) components[name] = block;
  }

  components.SiteHeader = SiteHeaderWidget;
  components.SiteFooter = SiteFooterWidget;

  for (const registration of registeredBlocks()) {
    if (!registration.layout) continue;
    Object.assign(components, registration.blocks);
    if (!registration.category) continue;
    const { key, title } = registration.category;
    categories[key] = {
      title,
      components: [...(categories[key]?.components ?? []), ...Object.keys(registration.blocks)],
    };
  }

  cachedConfig = {
    ...pageConfig,
    root: {
      fields: {},
      defaultProps: {},
      render: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    },
    categories,
    components,
  } as unknown as Config;
  cachedVersion = registryVersion();
  return cachedConfig;
}

export const emptyLayoutData = { content: [], root: { props: {} } };
