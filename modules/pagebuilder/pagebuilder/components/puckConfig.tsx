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

import { ButtonBlock } from './blocks/Button';
import { ColumnsBlock, type ColumnsProps } from './blocks/Columns';
import { HeadingBlock } from './blocks/Heading';
import { ImageBlock } from './blocks/Image';
import { SpacerBlock } from './blocks/Spacer';
import { TextBlock } from './blocks/Text';
import { ArticleCardsWidget } from './widgets/article-cards-widget';
import { CallToActionWidget } from './widgets/call-to-action-widget';
import { ContactCardsWidget } from './widgets/contact-cards-widget';
import { ContactFormWidget } from './widgets/contact-form-widget';
import { DividerWidget } from './widgets/divider-widget';
import { EyebrowSectionWidget } from './widgets/eyebrow-section-widget';
import { FaqWidget } from './widgets/faq-widget';
import { FeatureCardsWidget } from './widgets/feature-cards-widget';
import { HeroWidget } from './widgets/hero-widget';
import { LogoCloudWidget } from './widgets/logo-cloud-widget';
import { MediaObjectWidget } from './widgets/media-object-widget';
import { PageHeaderWidget } from './widgets/page-header-widget';
import { StatsWidget } from './widgets/stats-widget';
import { TagsWidget } from './widgets/tags-widget';

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
 * A block's own props, recovered from its render signature.
 *
 * Puck calls `render` with the props wrapped as `WithId<WithPuckProps<P>>`,
 * but `Config` is keyed by the *unwrapped* P — it applies that wrapper itself.
 * Feeding it the render params instead double-wraps every entry, which is why
 * the three injected keys come off here.
 */
type WidgetProps<T extends { render: (props: never) => unknown }> = Omit<
  Parameters<T['render']>[0],
  'id' | 'puck' | 'editMode'
>;

/**
 * Slot-bearing blocks can't use `WidgetProps` and must name their props type
 * directly.
 *
 * Puck maps a `Slot` (the stored array) to a `SlotComponent` (a renderable) on
 * its way into `render`, and that mapping is one-way — recovering the props
 * from the render signature yields the component form, which is not what
 * `defaultProps` and the stored data use. `Columns` is the only such block
 * today; the widened `Config` key below is deliberate, not an oversight.
 */

type PuckComponents = {
  Heading: WidgetProps<typeof HeadingBlock>;
  Text: WidgetProps<typeof TextBlock>;
  Image: WidgetProps<typeof ImageBlock>;
  Button: WidgetProps<typeof ButtonBlock>;
  Columns: ColumnsProps;
  Spacer: WidgetProps<typeof SpacerBlock>;
  PageHeader: WidgetProps<typeof PageHeaderWidget>;
  Hero: WidgetProps<typeof HeroWidget>;
  EyebrowSection: WidgetProps<typeof EyebrowSectionWidget>;
  MediaObject: WidgetProps<typeof MediaObjectWidget>;
  CallToAction: WidgetProps<typeof CallToActionWidget>;
  FeatureCards: WidgetProps<typeof FeatureCardsWidget>;
  Faq: WidgetProps<typeof FaqWidget>;
  Stats: WidgetProps<typeof StatsWidget>;
  ArticleCards: WidgetProps<typeof ArticleCardsWidget>;
  ContactCards: WidgetProps<typeof ContactCardsWidget>;
  ContactForm: WidgetProps<typeof ContactFormWidget>;
  LogoCloud: WidgetProps<typeof LogoCloudWidget>;
  Tags: WidgetProps<typeof TagsWidget>;
  Divider: WidgetProps<typeof DividerWidget>;
};

/**
 * Puck 0.20 replaced the positional generics (`Config<Components, Root>`) with
 * a single params object. The old form still resolves, but only the new one
 * carries the category and field slots, so this is the shape to extend.
 */
type PageConfig = Config<{ components: PuckComponents; root: PageRootProps }>;

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
  categories: {
    typography: { components: ['Heading', 'Text'] },
    media: { components: ['Image'] },
    actions: { components: ['Button'] },
    layout: { components: ['Columns', 'Spacer', 'Divider'] },
    sections: {
      title: 'Sections',
      components: ['PageHeader', 'Hero', 'EyebrowSection', 'MediaObject', 'CallToAction'],
    },
    collections: {
      title: 'Collections',
      components: ['FeatureCards', 'Faq', 'Stats', 'ArticleCards', 'ContactCards', 'LogoCloud'],
    },
    forms: { title: 'Forms', components: ['ContactForm', 'Tags'] },
  },
  // This map used to need a blanket cast: `PuckComponents` was keyed by each
  // block's *render* params, which Puck then wrapped a second time, and the
  // resulting mismatch was invariant so no entry would assign. Keying it by
  // the unwrapped props (see `WidgetProps`) makes every entry check on its
  // own, so a widget whose config drifts from its props now fails here.
  components: {
    Heading: HeadingBlock,
    Text: TextBlock,
    Image: ImageBlock,
    Button: ButtonBlock,
    Columns: ColumnsBlock,
    Spacer: SpacerBlock,
    PageHeader: PageHeaderWidget,
    Hero: HeroWidget,
    EyebrowSection: EyebrowSectionWidget,
    MediaObject: MediaObjectWidget,
    CallToAction: CallToActionWidget,
    FeatureCards: FeatureCardsWidget,
    Faq: FaqWidget,
    Stats: StatsWidget,
    ArticleCards: ArticleCardsWidget,
    ContactCards: ContactCardsWidget,
    ContactForm: ContactFormWidget,
    LogoCloud: LogoCloudWidget,
    Tags: TagsWidget,
    Divider: DividerWidget,
  },
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
