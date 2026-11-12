/**
 * The public surface of `@simple-module-py/pagebuilder`: what a module that
 * contributes Puck blocks imports from its `pagebuilder-blocks.ts` and the
 * files that one pulls in (#337). Anything not exported here is internal and
 * may move without notice; `scripts/check_ts_imports.py` refuses a sibling's
 * deep import into this package.
 *
 * Keep it light. A contributor's blocks are registered eagerly at app start,
 * so everything this file imports reaches the entry chunk of every public
 * page. Nothing here may import the editor (`puckConfig`, `editor/`, pages):
 * Puck itself appears only as `import type`. Pagebuilder's own files never
 * import this file, so it cannot form a cycle with them.
 */

// Registering blocks.
export type { AnyBlock, BlockRegistration } from './ui/components/blockRegistry';
export { registeredBlocks, registerPuckBlocks } from './ui/components/blockRegistry';
export { lazyBlock } from './ui/components/lazyBlock';
export type {
  ArticleCardItem,
  ArticleCardsWidgetProps,
} from './ui/components/widgets/article-cards-render';
// Render building blocks a contributed block reuses.
export { ArticleCardsGrid } from './ui/components/widgets/article-cards-render';
export type {
  SectionProps,
  SectionSpacing,
  SectionVariant,
} from './ui/components/widgets/_shared/section';
export { Section } from './ui/components/widgets/_shared/section';
export type { StatItem, StatsWidgetProps } from './ui/components/widgets/stats-widget';
export { StatsView } from './ui/components/widgets/stats-widget';
// Editor fields backed by pagebuilder's media library.
export type { FileItem, FilePickerAdapter } from './ui/fields';
export { createImageField, mediaLibraryAdapter } from './ui/fields';
// Link sanitising, so a contributed block treats URLs as pagebuilder's do.
export { isSafeHref, safeHref } from './ui/utils/markdown-links';
