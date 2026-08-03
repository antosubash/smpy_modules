import type { Config } from '@measured/puck';

import { puckConfig } from './puckConfig';
import { SiteFooterWidget } from './widgets/site-footer-widget';
import { SiteHeaderWidget } from './widgets/site-header-widget';

// Header / footer slots reuse the page's component palette minus heavy
// layout blocks (Columns), and replace the page-shaped root with a
// transparent pass-through so the host wrapper (<header>/<footer>)
// controls layout instead of Puck's default page container.
const { Columns: _drop, ...layoutComponents } = puckConfig.components;

export const layoutPuckConfig = {
  ...puckConfig,
  root: {
    fields: {},
    defaultProps: {},
    render: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  },
  categories: {
    // Site chrome is registered here and NOT in the page palette: a nav bar
    // dropped into the middle of a page would render a second one under the
    // real header.
    chrome: { title: 'Site chrome', components: ['SiteHeader', 'SiteFooter'] },
    typography: { components: ['Heading', 'Text'] },
    media: { components: ['Image'] },
    actions: { components: ['Button'] },
    // The partner strip under the GCA footer is this widget rather than
    // markup baked into SiteFooter, so an author can reorder or drop it.
    collections: { title: 'Collections', components: ['LogoCloud'] },
    layout: { components: ['Spacer', 'Divider'] },
  },
  components: {
    ...layoutComponents,
    SiteHeader: SiteHeaderWidget,
    SiteFooter: SiteFooterWidget,
  },
} as unknown as Config;

export const emptyLayoutData = { content: [], root: { props: {} } };
