import type { FieldPath } from './extract';

// Objects and arrays are both indexable by a path segment — `obj["key"]` and
// `arr[2]` alike — and arrays are `typeof === "object"`, so one guard covers
// both.
function isIndexable(value: unknown): value is Record<PropertyKey, unknown> {
  return typeof value === 'object' && value !== null;
}

/**
 * Write `translations[n]` back to the location `paths[n]` recorded, and
 * re-serialize.
 *
 * The exact inverse of `extractTranslatableStrings`: feeding it the strings
 * that function just extracted reproduces the input structurally. Props not
 * named in `paths` are never touched, so a translation pass can't quietly
 * rewrite a URL or drop a field it didn't understand.
 */
export function applyTranslatedStrings(
  puckJson: string,
  paths: FieldPath[],
  translations: string[],
): string {
  const parsed: unknown = JSON.parse(puckJson);

  paths.forEach((path, index) => {
    const translation = translations[index];
    // Loose equality catches `undefined` (array shorter than `paths`) and a
    // literal JSON `null` alike. Either way the original stands — writing
    // `null` over real copy is the one outcome worse than not translating.
    if (translation == null || path.length === 0) return;

    // Walk to the container that directly holds the final segment.
    let current: unknown = parsed;
    for (let i = 0; i < path.length - 1; i++) {
      if (!isIndexable(current)) return;
      current = current[path[i]];
    }
    if (!isIndexable(current)) return;

    current[path[path.length - 1]] = translation;
  });

  return JSON.stringify(parsed);
}
