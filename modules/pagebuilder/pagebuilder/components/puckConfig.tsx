/**
 * Shared Puck configuration consumed by both `<Puck>` (editor) and
 * `<Render>` (public viewer). The same component definitions are used
 * in both places so what authors see in the editor matches what
 * visitors see on the published page.
 */

import type { Config } from '@puckeditor/core';

import {
  type BlockRegistration,
  declareBuiltInBlocks,
  registeredBlocks,
  registryVersion,
} from './blockRegistry';

import { type CatalogProps, catalogCategories, catalogComponents } from './widgetCatalog';

export interface PageRootProps {
  title: string;
  /**
   * `contained` keeps the original max-w-4xl column, which every page built
   * before the section widgets existed relies on. `full` removes it: the
   * ported widgets are full-bleed sections that bring their own container,
   * and nesting them in a 4xl column crushes them.
   */
  width: 'contained' | 'full';
}

/**
 * Puck 0.20 replaced the positional generics (`Config<Components, Root>`) with
 * a single params object. The old form still resolves, but only the new one
 * carries the category and field slots, so this is the shape to extend.
 */
type PageConfig = Config<{ components: CatalogProps; root: PageRootProps }>;

export const basePageConfig: PageConfig = {
  root: {
    fields: {
      title: { type: 'text' },
      width: {
        type: 'radio',
        options: [
          { label: 'Contained', value: 'contained' },
          { label: 'Full width', value: 'full' },
        ],
      },
    },
    // The design pack used to be a root prop here. It is a site-wide branding
    // setting now — one site, one look — so PublicPage applies its root class
    // around the whole document instead, which is also what lets the header
    // and footer adopt it.
    defaultProps: { title: 'Untitled page', width: 'contained' },
    render: ({ children, width }) => (
      <div className={width === 'full' ? undefined : 'max-w-4xl mx-auto p-6'}>{children}</div>
    ),
  },
  categories: catalogCategories,
  components: catalogComponents,
};

// Names pagebuilder itself ships. Declared rather than duplicated in the
// registry so there is only one list to keep in sync, and so a module that
// tries to register one of these fails loudly instead of shadowing it.
declareBuiltInBlocks(Object.keys(basePageConfig.components));

/** Merge a registration's blocks and category into an accumulating config. */
function applyRegistration(
  components: Record<string, unknown>,
  categories: Record<string, { title?: string; components: string[] }>,
  registration: BlockRegistration,
): void {
  Object.assign(components, registration.blocks);
  if (!registration.category) return;
  const { key, title } = registration.category;
  categories[key] = {
    title,
    components: [...(categories[key]?.components ?? []), ...Object.keys(registration.blocks)],
  };
}

let cachedConfig: PageConfig | null = null;
let cachedVersion = -1;

/**
 * The page palette: pagebuilder's own blocks plus whatever modules registered.
 *
 * Memoised on the registry version rather than unconditionally — caching on
 * first call would silently drop any block registered after the first render.
 * Call it inside a component, never at module scope.
 */
export function getPuckConfig(): PageConfig {
  if (cachedConfig && cachedVersion === registryVersion()) return cachedConfig;
  const components: Record<string, unknown> = { ...basePageConfig.components };
  const categories = { ...basePageConfig.categories } as Record<
    string,
    { title?: string; components: string[] }
  >;
  for (const registration of registeredBlocks()) {
    applyRegistration(components, categories, registration);
  }
  cachedConfig = { ...basePageConfig, categories, components } as PageConfig;
  cachedVersion = registryVersion();
  return cachedConfig;
}

export const emptyData = {
  content: [],
  root: { props: { title: 'Untitled page', width: 'contained' } },
};

/**
 * Editor preview viewports surfaced as a switcher in the Puck toolbar.
 * The pixel widths match common mobile/tablet/desktop breakpoints rather
 * than specific devices so the preview reflects what visitors see.
 */
export const editorViewports = [
  { width: 360, height: 640, label: 'Mobile', icon: 'Smartphone' },
  { width: 768, height: 1024, label: 'Tablet', icon: 'Tablet' },
  { width: 1280, height: 800, label: 'Desktop', icon: 'Monitor' },
];
