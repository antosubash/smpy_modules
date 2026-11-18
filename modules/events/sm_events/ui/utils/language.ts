/** A language's own name in the console's language ("German"), else its code. */
export function languageName(code: string, ui?: string): string {
  try {
    return new Intl.DisplayNames(ui ? [ui, 'en'] : ['en'], { type: 'language' }).of(code) ?? code;
  } catch {
    return code;
  }
}
