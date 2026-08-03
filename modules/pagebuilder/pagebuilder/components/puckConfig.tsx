/**
 * Shared Puck configuration consumed by both `<Puck>` (editor) and
 * `<Render>` (public viewer). The same component definitions are used
 * in both places so what authors see in the editor matches what
 * visitors see on the published page.
 */

import type { Config } from '@measured/puck';

import { ButtonBlock } from './blocks/Button';
import { ColumnsBlock } from './blocks/Columns';
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
  /**
   * Adds the design pack's root class. The pack's CSS is scoped to it, so a
   * page opts in rather than the tokens applying site-wide.
   */
  designPack: 'base' | 'gca';
}

type WidgetProps<T extends { render: (props: never) => unknown }> = Parameters<T['render']>[0];

type PuckComponents = {
  Heading: Parameters<typeof HeadingBlock.render>[0];
  Text: Parameters<typeof TextBlock.render>[0];
  Image: Parameters<typeof ImageBlock.render>[0];
  Button: Parameters<typeof ButtonBlock.render>[0];
  Columns: Parameters<typeof ColumnsBlock.render>[0];
  Spacer: Parameters<typeof SpacerBlock.render>[0];
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

export const puckConfig: Config<PuckComponents, PageRootProps> = {
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
      designPack: {
        type: 'radio',
        options: [
          { label: 'Base', value: 'base' },
          { label: 'Canopy Atlas', value: 'gca' },
        ],
      },
    },
    defaultProps: { title: 'Untitled page', width: 'contained', designPack: 'base' },
    render: ({ children, width, designPack }) => (
      <div
        className={[
          width === 'full' ? '' : 'max-w-4xl mx-auto p-6',
          designPack === 'gca' ? 'gca-root' : '',
        ]
          .filter(Boolean)
          .join(' ')}
      >
        {children}
      </div>
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
  // Puck's Config expects each entry as ComponentConfig<WithId<WithPuckProps<P>>>
  // while a widget declares ComponentConfig<P>. Its `defaultProps` makes the
  // generic invariant, so every entry fails to assign even though the runtime
  // shape is right. Upstream hits this too and casts the same way. One cast
  // here keeps the per-widget types honest.
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
  } as unknown as Config<PuckComponents, PageRootProps>['components'],
};

export const emptyData = {
  content: [],
  root: { props: { title: 'Untitled page', width: 'contained', designPack: 'base' } },
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
