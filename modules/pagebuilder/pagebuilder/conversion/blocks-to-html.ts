/**
 * Render a page's blocks as a plain HTML string — for an export, a feed item,
 * or an email, where the React tree isn't available.
 *
 * Only blocks with a meaningful HTML equivalent convert. A hero or a layout
 * block has no honest flat representation, so rather than emit something
 * lossy and quiet, they're skipped and named in `lossyTypes` — the caller can
 * then say exactly what didn't come across.
 */

import { escapeHtml, markdownToHtml } from '../utils/markdown';
import type { PuckBlock } from './types';

export type BlocksToHtmlResult = { html: string; lossyTypes: string[] };

/** `h3` (what we store) and `3` (what upstream stores) both mean the same. */
function headingLevel(raw: unknown): string {
  const match = /^h?([1-6])$/.exec(String(raw ?? ''));
  return match ? match[1] : '2';
}

export function blocksToHtml(blocks: PuckBlock[]): BlocksToHtmlResult {
  const parts: string[] = [];
  const lossy = new Set<string>();

  for (const block of blocks) {
    const html = blockToHtml(block);
    if (html === null) {
      lossy.add(block.type);
    } else if (html) {
      parts.push(html);
    }
  }
  return { html: parts.join('\n'), lossyTypes: [...lossy] };
}

function blockToHtml(block: PuckBlock): string | null {
  const props = block.props ?? {};
  switch (block.type) {
    case 'Html':
      return typeof props.html === 'string' ? props.html : null;

    // Text and Markdown both hold markdown here — Text is the light inline
    // subset, Markdown the full block syntax — so both go through the same
    // converter, which escapes as it goes. Upstream has to sniff Text for a
    // leading tag because its Text field stores HTML; ours never does.
    case 'Text':
      return typeof props.text === 'string' ? markdownToHtml(props.text) : null;
    case 'Markdown':
      return typeof props.content === 'string' ? markdownToHtml(props.content) : null;

    case 'Heading': {
      if (typeof props.text !== 'string') return null;
      const level = headingLevel(props.level);
      return `<h${level}>${escapeHtml(props.text)}</h${level}>`;
    }

    case 'Image': {
      if (typeof props.src !== 'string') return null;
      const alt = typeof props.alt === 'string' ? props.alt : '';
      // `width`/`height` are carried through when known: without them a
      // consumer laying the HTML out has to load the image to size it, which
      // is the reflow the picker stores those numbers to avoid.
      const dims = ['width', 'height']
        .map((key) => (typeof props[key] === 'number' ? ` ${key}="${props[key]}"` : ''))
        .join('');
      return `<img src="${escapeHtml(props.src)}" alt="${escapeHtml(alt)}"${dims}>`;
    }

    case 'Quote': {
      if (typeof props.quote !== 'string') return null;
      const cite = ['author', 'source']
        .map((key) => (typeof props[key] === 'string' ? props[key].trim() : ''))
        .filter(Boolean)
        .join(', ');
      const attribution = cite ? `<footer>${escapeHtml(cite)}</footer>` : '';
      return `<blockquote><p>${escapeHtml(props.quote)}</p>${attribution}</blockquote>`;
    }

    default:
      return null;
  }
}
