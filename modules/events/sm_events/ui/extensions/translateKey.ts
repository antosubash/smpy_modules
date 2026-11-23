import type { Translate } from '../utils/i18n';

/** A plugin's label key, resolved at render (a registration is a module-scope constant, so it
 *  holds the key and never the text). A key no catalogue has comes back as itself from `t`:
 *  `fallback` (the plugin's id) is shown instead of a dotted key. */
export function translateKey(
  t: Translate,
  key: string | null | undefined,
  fallback: string,
): string {
  if (!key) return fallback;
  const text = t(key);
  return text && text !== key ? text : fallback;
}
