/**
 * The blocks an article body is made of.
 *
 * Deliberately a *prose* palette, not a copy of pagebuilder's widget catalogue.
 * That catalogue exists to build pages — heroes, feature grids, logo clouds,
 * site headers — and almost none of it belongs in a news story. Cloning it to
 * avoid depending on it would have been the worst of both options: the same
 * maintenance surface, twice, for blocks nobody puts in an article.
 *
 * The bar for adding one here is that a newsroom already does this thing in a
 * story and currently has to fake it with a paragraph: a summary box, a
 * correction, a table of figures, a dated sequence, a list of sources. A block
 * that only changes how something looks is a page-building widget wearing a
 * different hat, and belongs in the other module.
 *
 * A host that wants the full palette on an article can still have it: install
 * pagebuilder, build the page there, and link to it. This is the set for
 * writing.
 *
 * Self-contained by design — Tailwind utilities and the framework's own theme
 * tokens only, no pagebuilder styles — because these render on the public
 * article page, which has to work on a host that never installed that module.
 * Split by file along the same lines the editor groups them by, so the palette
 * a writer sees and the source are organised the same way.
 */

export {
  CalloutBlock,
  type CalloutProps,
  type CalloutTone,
  KeyPointsBlock,
  type KeyPointsProps,
  SourcesBlock,
  type SourcesProps,
} from './asides';
export {
  CodeBlock,
  type CodeProps,
  TableBlock,
  type TableProps,
  TimelineBlock,
  type TimelineProps,
} from './data';
export { DividerBlock, type DividerProps } from './layout';
export {
  EmbedBlock,
  type EmbedProps,
  GalleryBlock,
  type GalleryProps,
  ImageBlock,
  type ImageProps,
} from './media';
export {
  HeadingBlock,
  type HeadingProps,
  ListBlock,
  type ListProps,
  ParagraphBlock,
  type ParagraphProps,
  QuoteBlock,
  type QuoteProps,
} from './text';
