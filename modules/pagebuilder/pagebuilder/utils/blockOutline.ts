/**
 * The page's blocks as a flat, readable list.
 *
 * On a narrow screen the outline is the only view of the page there is — the
 * canvas needs width to drag on — so it has to answer "which block is this"
 * from the stored data alone, without rendering anything.
 */

import type { Data } from '@puckeditor/core';

export interface OutlineEntry {
  /** Puck's own block id. Stable across a reorder, so it keys the list. */
  id: string;
  type: string;
  label: string;
  /** A few words of the block's own content, to tell two of a kind apart. */
  summary: string;
}

interface ContentItem {
  type: string;
  props?: Record<string, unknown>;
}

function contentOf(data: Data | null | undefined): ContentItem[] {
  const content = (data as { content?: unknown } | null | undefined)?.content;
  return Array.isArray(content) ? (content as ContentItem[]) : [];
}

/**
 * Palette labels by block name, read off a Puck config.
 *
 * The outline names a block the way the palette the author added it from
 * does. Anything else invents a second vocabulary for the same thing.
 */
export function blockLabels(components: Record<string, unknown>): Record<string, string> {
  const labels: Record<string, string> = {};
  for (const [name, component] of Object.entries(components ?? {})) {
    const label = (component as { label?: unknown } | null)?.label;
    if (typeof label === 'string' && label) labels[name] = label;
  }
  return labels;
}

/**
 * `CallToAction` -> `Call to action`.
 *
 * The fallback for a block whose config carries no label — a module can
 * register one without setting it, and the stored `type` is then the only
 * name there is. Splitting it is the difference between an outline that reads
 * and one that shouts in camel case.
 */
export function humanizeBlockType(type: string): string {
  const spaced = type.replace(/([a-z0-9])([A-Z])/g, '$1 $2').trim();
  if (!spaced) return type;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
}

/** Props that name a block, best first. Checked before falling back to length. */
const NAMING_PROPS = [
  'title',
  'heading',
  'headline',
  'label',
  'text',
  'caption',
  'alt',
  'name',
  'body',
] as const;

const MAX_SUMMARY = 60;

function asText(value: unknown): string {
  return typeof value === 'string' ? value.trim().replace(/\s+/g, ' ') : '';
}

function clamp(text: string): string {
  return text.length > MAX_SUMMARY ? `${text.slice(0, MAX_SUMMARY - 1)}…` : text;
}

/**
 * A phrase identifying one block among its siblings.
 *
 * Named props are checked before the longest-string fallback on purpose: an
 * Image block's longest string is its `src`, and a URL is a worse answer to
 * "which block is this" than its alt text, even a short one.
 */
export function summarizeProps(props: Record<string, unknown> | undefined): string {
  if (!props) return '';
  for (const key of NAMING_PROPS) {
    const text = asText(props[key]);
    if (text) return clamp(text);
  }
  let longest = '';
  for (const [key, value] of Object.entries(props)) {
    if (key === 'id') continue;
    const text = asText(value);
    if (text.length > longest.length) longest = text;
  }
  return longest.length > 2 ? clamp(longest) : '';
}

export function outlineOf(
  data: Data | null | undefined,
  labels: Record<string, string> = {},
): OutlineEntry[] {
  return contentOf(data).map((item, index) => ({
    id: asText(item.props?.id) || `block-${index}`,
    type: item.type,
    label: labels[item.type] || humanizeBlockType(item.type),
    summary: summarizeProps(item.props),
  }));
}

/**
 * The same data with one block stepped one place up (-1) or down (+1).
 *
 * A move off either end returns the input unchanged rather than throwing, so
 * the first row's "up" and the last row's "down" need no special case at the
 * call site beyond being disabled.
 */
export function moveBlock(data: Data, from: number, direction: -1 | 1): Data {
  const content = [...contentOf(data)];
  const to = from + direction;
  if (from < 0 || from >= content.length || to < 0 || to >= content.length) return data;
  const [moved] = content.splice(from, 1);
  content.splice(to, 0, moved);
  return { ...data, content } as unknown as Data;
}
