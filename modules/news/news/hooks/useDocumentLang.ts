import { useEffect } from 'react';

/** Make `<html lang>` the language of the page on screen.
 *
 * The host shell says `lang="en"` for every screen, and the server rewrites it
 * for a fresh document (`endpoints/public/_lang.py`). This covers what the
 * server cannot: an Inertia visit between languages swaps the page component
 * without a new shell, so the attribute would otherwise stay on the language
 * the reader arrived in.
 */
export function useDocumentLang(locale: string | undefined): void {
  useEffect(() => {
    if (locale) document.documentElement.lang = locale;
  }, [locale]);
}
