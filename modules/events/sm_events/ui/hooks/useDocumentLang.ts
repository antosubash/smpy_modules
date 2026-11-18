import { useEffect } from 'react';

/** Make `<html lang>` the language of the page on screen.
 *
 *  The host shell says `lang="en"` for every screen and the server rewrites it for a fresh
 *  document (`_head.set_html_lang`). This covers a visit between languages inside the SPA,
 *  where the page component changes and no new shell is served. */
export function useDocumentLang(locale: string | undefined): void {
  useEffect(() => {
    if (!locale) return;
    const root = document.documentElement;
    // The shell's own language, which the server records beside the rewritten one.
    const shell = root.dataset.shellLang || root.lang;
    root.lang = locale;
    return () => {
      root.lang = shell;
    };
  }, [locale]);
}
