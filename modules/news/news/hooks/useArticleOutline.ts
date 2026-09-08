/**
 * The canvas's outline, with an identity that only moves when the outline does.
 *
 * `<Puck metadata>` is a store input, not a prop: a new object reaches
 * `appStore.setState`, and every block on the canvas is subscribed to that
 * store. The canvas re-renders on each keystroke — `useArticleBody` holds the
 * document in state — so handing Puck a freshly built array would push a store
 * write, and a full canvas re-render, through every character typed into a
 * paragraph.
 *
 * Comparing the serialised outline keeps that to the moments a heading actually
 * changes. Serialised rather than compared field by field because it is the
 * whole array that matters and `JSON.stringify` cannot drift out of step with
 * the shape the way a hand-written comparison would.
 */

import { useRef } from 'react';

import {
  articleOutline,
  type DocumentLike,
  type OutlineEntry,
} from '../components/body/blocks/outline';

export function useArticleOutline(data: DocumentLike | null | undefined): OutlineEntry[] {
  const cached = useRef<{ key: string; outline: OutlineEntry[] } | null>(null);
  const outline = articleOutline(data);
  const key = JSON.stringify(outline);
  if (!cached.current || cached.current.key !== key) {
    cached.current = { key, outline };
  }
  return cached.current.outline;
}
