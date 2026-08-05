import type { Field } from '@puckeditor/core';

/** Puck field types whose values are free-form human copy worth translating. */
export const TRANSLATABLE_TEXT_TYPES: ReadonlySet<string> = new Set([
  'text',
  'textarea',
  'richtext',
]);

// Key-based denylist: a `text`-typed field can still hold a URL, a colour or an
// id rather than copy (FeatureCards.items[].linkHref, Button.color). Applied on
// top of the type check so those are never sent to a translator even though
// Puck models them as plain text.
const DENYLIST_PATTERNS: readonly RegExp[] = [
  /href$/i,
  /url$/i,
  /src$/i,
  /colou?r$/i,
  /bg$/i,
  /^id$/i,
  // `srcset` and `sizes` are responsive-image descriptors —
  // "/img-800.png 800w, /img-1600.png 1600w" and "(max-width: 600px) 100vw".
  // `/src$/i` is end-anchored so it does not catch `srcset`, and nothing
  // catches `sizes`. A translator handed either returns something reflowed,
  // and the browser then requests a URL that doesn't exist.
  /^srcset$/i,
  /^sizes$/i,
  // CSS lengths: `height` (Html, Iframe), `bodyMaxWidth` (MediaObject). Any
  // casing, so `maxWidth` and `minHeight` are covered too.
  /(^|[a-z])(width|height)$/i,
  // The Html widget's field is raw markup, not prose. Sending it out for
  // translation gets the tags rewritten along with the words.
  /^html$/i,
  // camelCase technical identifiers (`questId`, `clusterId`). Anchored to a
  // capital `I` so it matches a real `…Id` suffix and never a lowercase word
  // that happens to end in "id" (`grid`, `valid`).
  /Id$/,
  // Numbered image-URL fields nested in arrays (DefinitionList's
  // items[].sections[].image1). The digit suffix means `src`/`url` above don't
  // match. Fully anchored so it hits exactly `image1` and never its genuine
  // alt-text sibling `image1Alt`.
  /^image\d+$/i,
];

function isDenylistedKey(key: string): boolean {
  return DENYLIST_PATTERNS.some((pattern) => pattern.test(key));
}

/**
 * True when `field` (found at prop `key`) holds translatable copy.
 *
 * Upstream also threads a per-component set of image-field names through here,
 * built from its `IMAGE_FIELDS` / `ARRAY_IMAGE_FIELDS` maps, because over there
 * an image field is declared as `type: "text"` and only swapped for the picker
 * when the config is assembled — so by name it is indistinguishable from copy.
 *
 * This module inlines `createImageField` at the field instead, which yields
 * `type: "custom"`. That fails the type check on the first line, so image
 * fields are excluded structurally and the whole map-plumbing is unnecessary
 * here. Worth knowing if these are ever diffed against each other.
 */
export function isTranslatableField(key: string, field: Field | undefined): boolean {
  if (!field || !TRANSLATABLE_TEXT_TYPES.has(field.type)) return false;
  return !isDenylistedKey(key);
}
