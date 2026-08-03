import type { Config } from '@measured/puck';

import { registeredBlocks, registryVersion } from './blockRegistry';
import { basePageConfig, getPuckConfig } from './puckConfig';
import { SiteFooterWidget } from './widgets/site-footer-widget';
import { SiteHeaderWidget } from './widgets/site-header-widget';

let cachedConfig: Config | null = null;
let cachedVersion = -1;

/**
 * The site-layout palette.
 *
 * Header / footer slots reuse the page's component palette minus heavy layout
 * blocks (Columns), and replace the page-shaped root with a transparent
 * pass-through so the host wrapper (`<header>`/`<footer>`) controls layout
 * instead of Puck's default page container.
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
  // From the *base* blocks, not the merged page palette: a module's page-only
  // registration must not leak into the header and footer. Only a
  // `layout: true` registration is added back below.
  const { Columns: _drop, ...layoutComponents } = basePageConfig.components;
  const components: Record<string, unknown> = { ...layoutComponents };
  const categories: Record<string, { title?: string; components: string[] }> = {
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
  };

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
