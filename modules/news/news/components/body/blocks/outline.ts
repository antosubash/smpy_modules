/**
 * The article's headings, derived once and handed to the blocks that need them.
 *
 * Puck gives a block its own props and nothing else — a `render` function
 * cannot see the block above it, which is why a contents list could not be
 * written here before. The seam is `metadata`: the two screens that mount the
 * document (`PublicArticle` and the `ArticleBody` canvas) already know the
 * whole document, so they compute the outline and pass it down, the same way
 * `Read next` learns which article it is inside.
 *
 * Both the `Contents` block and the `Heading` block read it, and that is the
 * point of deriving it in one place: an anchor a contents entry links to has to
 * be the anchor the heading renders, on both screens, or exactly one of them
 * gets working links.
 */

import { slugify } from '../../../utils/slugify';

/** The component key headings are registered under in `articlePuckConfig`. */
export const HEADING_TYPE = 'Heading';

/** Where the `metadata` bag carries the outline. */
export const OUTLINE_KEY = 'outline';

/** What a heading slugifies to when nothing survives the fold — a title in a
 *  script `slugify` drops entirely still needs an address to link to. */
const FALLBACK_ANCHOR = 'section';

export interface OutlineEntry {
  /** The heading block's Puck id. How a heading finds *its own* entry. */
  blockId: string;
  /** The `id` the heading renders and a contents entry links to. */
  anchor: string;
  text: string;
  level: 2 | 3;
}

/** One section and the sub-sections under it. */
export interface OutlineSection {
  entry: OutlineEntry;
  children: OutlineEntry[];
}

interface ContentItem {
  type?: string;
  props?: Record<string, unknown>;
}

/** Just enough of Puck's `Data` to walk it — the callers hold the real type,
 *  and a document loaded from the server is `Record<string, unknown>` anyway. */
export interface DocumentLike {
  content?: unknown;
}

/**
 * An anchor for `text` that no earlier heading in the document has taken.
 *
 * The suffix search is a loop rather than a counter because a writer can type
 * the very string the counter would invent: "Background", "Background" and
 * "Background 2" all want `background-2`, and handing the same id to two
 * elements sends every link to whichever the browser finds first.
 */
function uniqueAnchor(text: string, used: Set<string>): string {
  const base = slugify(text) || FALLBACK_ANCHOR;
  let anchor = base;
  let suffix = 2;
  while (used.has(anchor)) {
    anchor = `${base}-${suffix}`;
    suffix += 1;
  }
  used.add(anchor);
  return anchor;
}

/**
 * Every written heading in the document, in the order a reader meets them.
 *
 * A heading with no text is left out rather than given a blank entry: it is a
 * block a writer has dropped and not filled in yet, and a contents list with an
 * empty row in it looks like the list is broken rather than the article.
 */
export function articleOutline(data: DocumentLike | null | undefined): OutlineEntry[] {
  const content = Array.isArray(data?.content) ? (data.content as ContentItem[]) : [];
  const used = new Set<string>();
  const entries: OutlineEntry[] = [];
  for (const item of content) {
    if (item?.type !== HEADING_TYPE) continue;
    const props = item.props ?? {};
    const text = typeof props.text === 'string' ? props.text.trim() : '';
    if (!text) continue;
    entries.push({
      blockId: typeof props.id === 'string' ? props.id : '',
      anchor: uniqueAnchor(text, used),
      text,
      level: props.level === '3' ? 3 : 2,
    });
  }
  return entries;
}

/** The outline out of a `puck.metadata` bag, or an empty one.
 *
 * Defensive because the bag is a `Record<string, any>` shared by every block:
 * a screen that mounts the document without passing an outline must render a
 * heading, not throw. */
export function outlineFromMetadata(metadata: unknown): OutlineEntry[] {
  const value = (metadata as Record<string, unknown> | undefined)?.[OUTLINE_KEY];
  return Array.isArray(value) ? (value as OutlineEntry[]) : [];
}

/**
 * The `id` a heading block should render, or `undefined` for no attribute.
 *
 * Looked up by block id rather than recomputed from the text, because only the
 * document knows whether this is the first "Background" or the second — the
 * heading itself cannot tell.
 *
 * The fallback covers a document rendered without an outline: the slug alone,
 * which is what the outline would have produced for a heading whose text is
 * unique. Two identical headings would collide there, but nothing links to them
 * in that case — the contents list is fed by the same outline that is missing.
 */
export function headingAnchor(
  blockId: string | undefined,
  text: string | undefined,
  outline: OutlineEntry[],
): string | undefined {
  const match = blockId ? outline.find((entry) => entry.blockId === blockId) : undefined;
  if (match) return match.anchor;
  return slugify((text ?? '').trim()) || undefined;
}

/**
 * The outline as sections, for a nested contents list.
 *
 * A sub-section before any section is promoted rather than dropped. An article
 * that opens on an H3 is unusual but it is what the writer typed, and silently
 * leaving it out of the contents makes the list disagree with the article.
 */
export function groupOutline(entries: OutlineEntry[], includeSub: boolean): OutlineSection[] {
  const sections: OutlineSection[] = [];
  for (const entry of entries) {
    const last = sections[sections.length - 1];
    if (entry.level === 3 && includeSub && last) {
      last.children.push(entry);
    } else if (entry.level === 2 || includeSub) {
      sections.push({ entry, children: [] });
    }
  }
  return sections;
}
