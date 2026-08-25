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
 */

import type { Config } from '@puckeditor/core';

import {
  DividerBlock,
  type DividerProps,
  EmbedBlock,
  type EmbedProps,
  HeadingBlock,
  type HeadingProps,
  ImageBlock,
  type ImageProps,
  ListBlock,
  type ListProps,
  ParagraphBlock,
  type ParagraphProps,
  QuoteBlock,
  type QuoteProps,
} from './articleBlocks';

export interface ArticleBodyProps {
  Heading: HeadingProps;
  Paragraph: ParagraphProps;
  Image: ImageProps;
  Quote: QuoteProps;
  List: ListProps;
  Divider: DividerProps;
  Embed: EmbedProps;
}

export interface ArticleRootProps {
  title: string;
}

/**
 * Puck 0.20 replaced the positional generics (`Config<Components, Root>`) with
 * a single params object. The old form still resolves, but only the new one
 * carries the category and field slots, so this is the shape to extend.
 */
type ArticleConfig = Config<{ components: ArticleBodyProps; root: ArticleRootProps }>;

export const articlePuckConfig: ArticleConfig = {
  root: {
    // No width switch, unlike a page. An article is prose: it reads at one
    // measure, and offering "full width" would only ever produce a story
    // nobody can follow across a wide monitor.
    fields: { title: { type: 'text' } },
    defaultProps: { title: 'Untitled article' },
    render: ({ children }) => <div className="mx-auto max-w-2xl px-4 py-8">{children}</div>,
  },
  categories: {
    text: { title: 'Text', components: ['Heading', 'Paragraph', 'List', 'Quote'] },
    media: { title: 'Media', components: ['Image', 'Embed'] },
    layout: { title: 'Layout', components: ['Divider'] },
  },
  components: {
    Heading: HeadingBlock,
    Paragraph: ParagraphBlock,
    Image: ImageBlock,
    Quote: QuoteBlock,
    List: ListBlock,
    Divider: DividerBlock,
    Embed: EmbedBlock,
  },
};

/** What the canvas opens for an article whose body has never been written.
 *
 * Mirrors `news.content.empty_article_document` on the server, which is what a
 * newly created article is given. Kept here as well because the canvas has to
 * mount even if a stored document is somehow null — an editor that renders
 * nothing is indistinguishable from one that failed to load.
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
  { width: 360, height: 640, label: 'Mobile', icon: 'Smartphone' },
  { width: 768, height: 1024, label: 'Tablet', icon: 'Tablet' },
  { width: 1280, height: 800, label: 'Desktop', icon: 'Monitor' },
];
