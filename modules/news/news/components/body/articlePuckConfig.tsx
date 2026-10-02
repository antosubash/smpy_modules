/**
 * The Puck configuration an article body is edited and rendered with.
 *
 * Shared by `<Puck>` (the canvas) and `<Render>` (the public viewer) so what a
 * writer sees while editing is what a reader gets — the same reason pagebuilder
 * shares one config between its two.
 *
 * Unlike that one, this config is a constant rather than something assembled
 * from a registry. Pagebuilder's palette is extensible because other modules
 * contribute blocks to it — news itself does. Nothing contributes to *this*
 * one: it is the set for writing an article, and a registry would be
 * machinery with no second caller.
 *
 * What belongs in the set is governed by `./blocks/index.ts`.
 */

import type { Config } from '@puckeditor/core';

import { keys } from '../../utils/i18n';

import {
  AudioBlock,
  type AudioProps,
  CalloutBlock,
  type CalloutProps,
  ChartBlock,
  type ChartProps,
  CodeBlock,
  type CodeProps,
  ComparisonBlock,
  type ComparisonProps,
  ContentsBlock,
  type ContentsProps,
  DefinitionsBlock,
  type DefinitionsProps,
  DividerBlock,
  type DividerProps,
  EmbedBlock,
  type EmbedProps,
  FactsBlock,
  type FactsProps,
  GalleryBlock,
  type GalleryProps,
  HeadingBlock,
  type HeadingProps,
  ImageBlock,
  type ImageProps,
  KeyPointsBlock,
  type KeyPointsProps,
  ListBlock,
  type ListProps,
  ParagraphBlock,
  type ParagraphProps,
  QandABlock,
  type QandAProps,
  QuoteBlock,
  type QuoteProps,
  RelatedBlock,
  type RelatedProps,
  SourcesBlock,
  type SourcesProps,
  TableBlock,
  type TableProps,
  TimelineBlock,
  type TimelineProps,
  VideoBlock,
  type VideoProps,
} from './blocks';

export interface ArticleBodyProps {
  Heading: HeadingProps;
  Paragraph: ParagraphProps;
  List: ListProps;
  Quote: QuoteProps;
  QandA: QandAProps;
  KeyPoints: KeyPointsProps;
  Callout: CalloutProps;
  Definitions: DefinitionsProps;
  Sources: SourcesProps;
  Related: RelatedProps;
  Contents: ContentsProps;
  Image: ImageProps;
  Gallery: GalleryProps;
  Comparison: ComparisonProps;
  Video: VideoProps;
  Audio: AudioProps;
  Embed: EmbedProps;
  Table: TableProps;
  Chart: ChartProps;
  Facts: FactsProps;
  Code: CodeProps;
  Timeline: TimelineProps;
  Divider: DividerProps;
}

/** The root edits nothing, so it declares nothing — see `articlePuckConfig`.
 *
 *  Spelt as an alias rather than an empty interface, which biome bans, and
 *  named so the `Config` line below still reads as "components plus a root".
 */
export type ArticleRootProps = Record<string, never>;

/**
 * Puck 0.20 replaced the positional generics (`Config<Components, Root>`) with
 * a single params object. The old form still resolves, but only the new one
 * carries the category and field slots, so this is the shape to extend.
 */
type ArticleConfig = Config<{ components: ArticleBodyProps; root: ArticleRootProps }>;

export const articlePuckConfig: ArticleConfig = {
  root: {
    // No fields at all, and the absence of `title` is the deliberate half.
    //
    // Puck offers a root field set, and a document root naturally wants a
    // title — but an article already has one, on `news_articles.title`, and
    // that is what the admin list, the `<title>`, the card and the public `h1`
    // are all drawn from. A root `title` here edited `draft_data.root.props`
    // instead, which this root's render ignores and the viewer never reads: a
    // writer renamed the article on the canvas, watched the field accept it,
    // and nothing moved. The headline is edited on the article screen, which is
    // the screen that can also move the URL along with it.
    //
    // No width switch either, unlike a page. An article is prose: it reads at
    // one measure, and offering "full width" would only ever produce a story
    // nobody can follow across a wide monitor.
    fields: {},
    render: ({ children }) => <div className="mx-auto max-w-2xl px-4 py-8">{children}</div>,
  },
  // Grouped by what a writer is reaching for, which is not the same as what the
  // block renders: Key points and Sources are both lists, and neither belongs
  // beside List, because a writer wanting a summary box is not shopping for a
  // list — they are looking for the thing that sits outside the story.
  categories: {
    text: {
      title: keys.news.blocks.categories.text,
      components: ['Heading', 'Paragraph', 'List', 'Quote', 'QandA'],
    },
    asides: {
      title: keys.news.blocks.categories.asides,
      components: ['KeyPoints', 'Callout', 'Definitions', 'Sources', 'Related', 'Contents'],
    },
    media: {
      title: keys.news.blocks.categories.media,
      components: ['Image', 'Gallery', 'Comparison', 'Video', 'Audio', 'Embed'],
    },
    data: {
      title: keys.news.blocks.categories.data,
      components: ['Table', 'Chart', 'Facts', 'Code', 'Timeline'],
    },
    layout: { title: keys.news.blocks.categories.layout, components: ['Divider'] },
  },
  components: {
    Heading: HeadingBlock,
    Paragraph: ParagraphBlock,
    List: ListBlock,
    Quote: QuoteBlock,
    QandA: QandABlock,
    KeyPoints: KeyPointsBlock,
    Callout: CalloutBlock,
    Definitions: DefinitionsBlock,
    Sources: SourcesBlock,
    Related: RelatedBlock,
    Contents: ContentsBlock,
    Image: ImageBlock,
    Gallery: GalleryBlock,
    Comparison: ComparisonBlock,
    Video: VideoBlock,
    Audio: AudioBlock,
    Embed: EmbedBlock,
    Table: TableBlock,
    Chart: ChartBlock,
    Facts: FactsBlock,
    Code: CodeBlock,
    Timeline: TimelineBlock,
    Divider: DividerBlock,
  },
};

/** What the canvas opens for an article whose body has never been written.
 *
 * Mirrors `news.content.empty_article_document` on the server, which is what a
 * newly created article is given. Kept here as well because the canvas has to
 * mount even if a stored document is somehow null — an editor that renders
 * nothing is indistinguishable from one that failed to load.
 *
 * The root still carries a `title` prop, which nothing renders. It stays
 * because every document ever saved has one and dropping it would only mean
 * writing documents that differ from the stored ones for no gain; what was
 * removed is the *field* that let a writer edit it, thinking they were renaming
 * the article.
 */
export const emptyArticleData = {
  content: [],
  root: { props: { title: 'Untitled article' } },
};

/**
 * Editor preview viewports surfaced as a switcher in the Puck toolbar.
 * The pixel widths match common mobile/tablet/desktop breakpoints rather
 * than specific devices so the preview reflects what readers see.
 */
export const articleViewports = [
  { width: 360, height: 640, label: keys.news.blocks.viewports.mobile, icon: 'Smartphone' },
  { width: 768, height: 1024, label: keys.news.blocks.viewports.tablet, icon: 'Tablet' },
  { width: 1280, height: 800, label: keys.news.blocks.viewports.desktop, icon: 'Monitor' },
];
