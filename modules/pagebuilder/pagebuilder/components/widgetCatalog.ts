/**
 * Every block pagebuilder ships, and where it sits in the editor palette.
 *
 * Split out of `puckConfig.tsx` because the catalogue is the part that grows:
 * the config file keeps the root definition and the registry merge, which are
 * a fixed size, while this list gains an entry per widget.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { keys } from '../utils/i18n';

import { ButtonBlock } from './blocks/Button';
import { ColumnsBlock } from './blocks/Columns';
import { HeadingBlock } from './blocks/Heading';
import { ImageBlock } from './blocks/Image';
import { SpacerBlock } from './blocks/Spacer';
import { TextBlock } from './blocks/Text';
import { AccordionWidget } from './widgets/accordion-widget';
import { AlertWidget } from './widgets/alert-widget';
import { AppStoreBadgesWidget } from './widgets/app-store-badges-widget';
import { ArticleCardsWidget } from './widgets/article-cards-widget';
import { CallToActionWidget } from './widgets/call-to-action-widget';
import { CarouselWidget } from './widgets/carousel-widget';
import { CenteredHeroWidget } from './widgets/centered-hero-widget';
import { ColoredActionListWidget } from './widgets/colored-action-list-widget';
import { ColumnWidget } from './widgets/column-widget';
import { ContactCardsWidget } from './widgets/contact-cards-widget';
import { ContactFormWidget } from './widgets/contact-form-widget';
import { ContainerWidget } from './widgets/container-widget';
import { DefinitionListWidget } from './widgets/definition-list-widget';
import { DividerWidget } from './widgets/divider-widget';
import { EyebrowSectionWidget } from './widgets/eyebrow-section-widget';
import { FaqWidget } from './widgets/faq-widget';
import { FeatureCardWidget } from './widgets/feature-card-widget';
import { FeatureCardsWidget } from './widgets/feature-cards-widget';
import { FeatureGridWidget } from './widgets/feature-grid-widget';
import { FeatureShowcaseWidget } from './widgets/feature-showcase-widget';
import { GalleryWidget } from './widgets/gallery-widget';
import { GridWidget } from './widgets/grid-widget';
import { HeroWidget } from './widgets/hero-widget';
import { HtmlWidget } from './widgets/html-widget';
import { IframeWidget } from './widgets/iframe-widget';
import { LeaderboardWidget } from './widgets/leaderboard-widget';
import { ListWidget } from './widgets/list-widget';
import { LogoCloudWidget } from './widgets/logo-cloud-widget';
import { MarkdownWidget } from './widgets/markdown-widget';
import { MediaObjectWidget } from './widgets/media-object-widget';
import { NewsletterWidget } from './widgets/newsletter-widget';
import { PageHeaderWidget } from './widgets/page-header-widget';
import { ProseSectionWidget } from './widgets/prose-section-widget';
import { QuoteWidget } from './widgets/quote-widget';
import { RowWidget } from './widgets/row-widget';
import { SectionIntroWidget } from './widgets/section-intro-widget';
import { SignupBannerWidget } from './widgets/signup-banner-widget';
import { SimpleActionListWidget } from './widgets/simple-action-list-widget';
import { SocialBannerWidget } from './widgets/social-banner-widget';
import { StatsWidget } from './widgets/stats-widget';
import { StepsWidget } from './widgets/steps-widget';
import { StoryCardsWidget } from './widgets/story-cards-widget';
import { TableWidget } from './widgets/table-widget';
import { TabsWidget } from './widgets/tabs-widget';
import { TagsWidget } from './widgets/tags-widget';
import { TestimonialWidget } from './widgets/testimonial-widget';
import { TimelineWidget } from './widgets/timeline-widget';
import { UnderConstructionWidget } from './widgets/under-construction-widget';
import { VideoWidget } from './widgets/video-widget';
import { WelcomeWidget } from './widgets/welcome-widget';

export const catalogComponents = {
  Accordion: AccordionWidget,
  Alert: AlertWidget,
  AppStoreBadges: AppStoreBadgesWidget,
  ArticleCards: ArticleCardsWidget,
  Button: ButtonBlock,
  CallToAction: CallToActionWidget,
  Carousel: CarouselWidget,
  CenteredHero: CenteredHeroWidget,
  ColoredActionList: ColoredActionListWidget,
  Column: ColumnWidget,
  Columns: ColumnsBlock,
  ContactCards: ContactCardsWidget,
  ContactForm: ContactFormWidget,
  Container: ContainerWidget,
  DefinitionList: DefinitionListWidget,
  Divider: DividerWidget,
  EyebrowSection: EyebrowSectionWidget,
  Faq: FaqWidget,
  FeatureCard: FeatureCardWidget,
  FeatureCards: FeatureCardsWidget,
  FeatureGrid: FeatureGridWidget,
  FeatureShowcase: FeatureShowcaseWidget,
  Gallery: GalleryWidget,
  Grid: GridWidget,
  Heading: HeadingBlock,
  Hero: HeroWidget,
  Html: HtmlWidget,
  Iframe: IframeWidget,
  Image: ImageBlock,
  Leaderboard: LeaderboardWidget,
  List: ListWidget,
  LogoCloud: LogoCloudWidget,
  Markdown: MarkdownWidget,
  MediaObject: MediaObjectWidget,
  Newsletter: NewsletterWidget,
  PageHeader: PageHeaderWidget,
  ProseSection: ProseSectionWidget,
  Quote: QuoteWidget,
  Row: RowWidget,
  SectionIntro: SectionIntroWidget,
  SignupBanner: SignupBannerWidget,
  SimpleActionList: SimpleActionListWidget,
  SocialBanner: SocialBannerWidget,
  Spacer: SpacerBlock,
  Stats: StatsWidget,
  Steps: StepsWidget,
  StoryCards: StoryCardsWidget,
  Table: TableWidget,
  Tabs: TabsWidget,
  Tags: TagsWidget,
  Testimonial: TestimonialWidget,
  Text: TextBlock,
  Timeline: TimelineWidget,
  UnderConstruction: UnderConstructionWidget,
  Video: VideoWidget,
  Welcome: WelcomeWidget,
};

/**
 * Each block's own props, recovered from its `ComponentConfig`.
 *
 * Derived rather than hand-listed: a parallel type map would be a second
 * 56-entry list to keep in step, and `ComponentConfig<P>` already carries `P`
 * in an inferable position. This also handles slot-bearing blocks correctly,
 * which a map keyed off the *render* signature cannot — Puck rewrites `Slot`
 * to `SlotComponent` on the way into `render`, and that mapping is one-way.
 */
type PropsOf<T> = T extends ComponentConfig<infer P> ? P : never;

export type CatalogProps = {
  [K in keyof typeof catalogComponents]: PropsOf<(typeof catalogComponents)[K]>;
};

/**
 * Palette grouping. `_hidden` is Puck's convention for a block that stays
 * usable in stored data but is not offered in the palette — `CenteredHero` is
 * a Hero variant reached through Hero's own fields, so offering both would
 * just be two doors to one room.
 *
 * Typed against the catalogue's own keys rather than `string`, so a category
 * naming a block that doesn't exist — or a block renamed out from under a
 * category — is a compile error instead of an entry that silently never
 * appears in the palette.
 */
type CatalogCategory = {
  title?: string;
  visible?: boolean;
  components: (keyof typeof catalogComponents)[];
};

export const catalogCategories: Record<string, CatalogCategory> = {
  typography: {
    components: ['Heading', 'Text', 'Markdown', 'ProseSection', 'Quote', 'List', 'DefinitionList'],
  },
  media: { components: ['Image', 'Gallery', 'Carousel', 'Video', 'Iframe'] },
  actions: {
    components: ['Button', 'SimpleActionList', 'ColoredActionList', 'AppStoreBadges'],
  },
  layout: {
    components: ['Columns', 'Container', 'Row', 'Column', 'Grid', 'Spacer', 'Divider'],
  },
  sections: {
    title: keys.pagebuilder.blocks.categories.sections,
    components: [
      'PageHeader',
      'Hero',
      'EyebrowSection',
      'MediaObject',
      'CallToAction',
      'SectionIntro',
      'FeatureShowcase',
      'Steps',
      'Timeline',
    ],
  },
  collections: {
    title: keys.pagebuilder.blocks.categories.collections,
    components: [
      'FeatureCards',
      'FeatureCard',
      'FeatureGrid',
      'Faq',
      'Stats',
      'ArticleCards',
      'ContactCards',
      'LogoCloud',
      'StoryCards',
      'Testimonial',
      'Leaderboard',
      'Table',
    ],
  },
  forms: {
    title: keys.pagebuilder.blocks.categories.forms,
    components: ['ContactForm', 'Tags', 'Newsletter', 'SignupBanner'],
  },
  interactive: {
    title: keys.pagebuilder.blocks.categories.interactive,
    components: ['Accordion', 'Tabs'],
  },
  utility: {
    title: keys.pagebuilder.blocks.categories.utility,
    components: ['Html', 'Alert', 'SocialBanner', 'UnderConstruction', 'Welcome'],
  },
  _hidden: { components: ['CenteredHero'], visible: false },
};
