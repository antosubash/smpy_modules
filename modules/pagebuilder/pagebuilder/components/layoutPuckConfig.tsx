import type { Config } from '@measured/puck';

import { puckConfig } from './puckConfig';

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
    typography: { components: ['Heading', 'Text'] },
    media: { components: ['Image'] },
    actions: { components: ['Button'] },
    layout: { components: ['Spacer'] },
  },
  components: layoutComponents,
} as unknown as Config;

export const emptyLayoutData = { content: [], root: { props: {} } };
