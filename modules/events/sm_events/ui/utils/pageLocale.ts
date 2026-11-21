import { createContext } from 'react';

/** The language a public page is written in, with its catalogue. Set by `<PageLocale>`; where it
 *  is absent (the console) `useT` keeps reading the framework's console language. */
export type PageCatalogue = {
  locale: string;
  t: (key: string, params?: Record<string, unknown>) => string;
};

export const PageCatalogueContext = createContext<PageCatalogue | null>(null);
