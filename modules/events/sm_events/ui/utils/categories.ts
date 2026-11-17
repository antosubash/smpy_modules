import type { Category } from './types';

/** A category's name for the console: the console language (`de-AT` also tries
 *  `de`), then the first content language, then the slug - never empty. */
export function categoryName(
  category: Category,
  consoleLocale: string | undefined,
  contentLocales: string[],
): string {
  const tries = [consoleLocale, consoleLocale?.split('-')[0], contentLocales[0]];
  for (const locale of tries) {
    const name = locale ? category.names[locale]?.trim() : undefined;
    if (name) return name;
  }
  return category.slug;
}
