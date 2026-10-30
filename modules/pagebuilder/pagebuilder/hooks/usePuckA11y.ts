/**
 * Fills accessibility gaps in Puck's own editor chrome (#235), which this
 * module renders but cannot change through Puck's override props:
 *
 * - the zoom select and an array field's add button have no accessible name;
 * - the plugin rail (Blocks, Outline, Fields) is clickable DIVs a keyboard
 *   cannot reach, so the Outline plugin — whose rows are buttons — is out of
 *   reach too;
 * - Enter on a focused canvas block does nothing, where a click selects it
 *   and opens its fields.
 *
 * Puck's markup is matched by the stable prefix of its CSS-module class
 * names (`_NavItem-link_<hash>`). Written against Puck 0.23;
 * `tests/e2e/pagebuilder-puck-a11y.spec.ts` fails if an upgrade renames
 * them, rather than this silently doing nothing.
 */

import { useEffect } from 'react';

const ZOOM = 'select[class*="_ViewportControls-zoomSelect_"]';
const ARRAY_ADD = 'button[class*="_ArrayField-addButton_"]';
const NAV_ITEM = '[class*="_NavItem-link_"]';

interface Labels {
  zoom: string;
  addItem: string;
}

function label(doc: Document, selector: string, name: string): void {
  for (const el of doc.querySelectorAll(selector)) {
    if (!el.getAttribute('aria-label')) el.setAttribute('aria-label', name);
  }
}

/** Plugin rail items become buttons a keyboard can reach and press. */
function navItems(doc: Document): void {
  for (const el of doc.querySelectorAll<HTMLElement>(NAV_ITEM)) {
    if (el.getAttribute('role') === 'button') continue;
    el.setAttribute('role', 'button');
    el.tabIndex = 0;
    el.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      el.click();
    });
  }
}

/**
 * Enter selects the canvas block that has focus, as a click does. Only when
 * the block's own wrapper has focus — a link, input or button inside an
 * authored block keeps its Enter. Space is left alone: it is the drag key.
 */
function onCanvasKey(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.defaultPrevented) return;
  // Not `instanceof Element`: a block in the iframe belongs to that frame's
  // realm, whose Element is a different class.
  const target = event.target as HTMLElement | null;
  if (typeof target?.hasAttribute !== 'function') return;
  if (!target.hasAttribute('data-puck-component')) return;
  event.preventDefault();
  target.click();
}

export function usePuckA11y(labels: Labels): void {
  const { zoom, addItem } = labels;
  useEffect(() => {
    // The canvas is a same-origin iframe in the page editor and part of the
    // document in the layout editor; listen in both.
    const docs = new Set<Document>();
    const frames = new WeakSet<HTMLIFrameElement>();
    const listen = (doc: Document) => {
      if (docs.has(doc)) return;
      docs.add(doc);
      doc.addEventListener('keydown', onCanvasKey);
    };
    listen(document);

    let frame = 0;
    const patch = () => {
      frame = 0;
      label(document, ZOOM, zoom);
      label(document, ARRAY_ADD, addItem);
      navItems(document);
      for (const iframe of document.querySelectorAll('iframe')) {
        if (!frames.has(iframe)) {
          frames.add(iframe);
          // A load can swap the frame's document without touching ours.
          iframe.addEventListener('load', () => {
            if (iframe.contentDocument) listen(iframe.contentDocument);
          });
        }
        if (iframe.contentDocument) listen(iframe.contentDocument);
      }
    };
    patch();
    // Puck renders these lazily (a field's add button appears when its block
    // is selected), so patch again after each change, once per frame.
    const observer = new MutationObserver(() => {
      if (!frame) frame = requestAnimationFrame(patch);
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
      for (const doc of docs) doc.removeEventListener('keydown', onCanvasKey);
    };
  }, [zoom, addItem]);
}
