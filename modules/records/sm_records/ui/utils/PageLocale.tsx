import { type ReactNode, Suspense, use, useMemo } from 'react';
import { english, flatten } from './i18n';
import { type PageCatalogue, PageCatalogueContext } from './pageLocale';

/**
 * Public forms speak the language of the page, not of the visitor's console (#488).
 *
 * Inside this provider `useT` reads records' own catalogue for the page's language: English is in
 * the bundle, every other language is one lazy chunk named in `loaders`, and a language without
 * one reads English.
 */
const loaders: Record<string, () => Promise<{ default: unknown }>> = {
  de: () => import('../../locales/de.json'),
};

type Flat = Record<string, string>;
const loaded = new Map<string, Flat>();
const pending = new Map<string, Promise<Flat>>();

function resolveLoaderKey(locale: string): string | undefined {
  if (locale in loaders) return locale;
  const lower = locale.toLowerCase();
  if (lower in loaders) return lower;
  const base = lower.split('-')[0];
  return base in loaders ? base : undefined;
}

/** Start loading a language's catalogue (preloaded on public pages; tests call it up front). */
export function loadCatalogue(locale: string): Promise<Flat> {
  const key = resolveLoaderKey(locale);
  const cacheKey = key ?? locale;
  const hit = pending.get(cacheKey);
  if (hit) return hit;
  const loader = key ? loaders[key] : undefined;
  const promise = (loader ? loader() : Promise.resolve({ default: {} }))
    .then((m) => {
      const flat = flatten(m.default as Record<string, unknown>, 'records', {});
      loaded.set(cacheKey, flat);
      return flat;
    })
    .catch((err) => {
      pending.delete(cacheKey);
      throw err;
    });
  pending.set(cacheKey, promise);
  return promise;
}

// Preload the page's catalogue as soon as this module runs when `<html lang>` names one.
if (typeof document !== 'undefined') {
  const docKey = resolveLoaderKey(document.documentElement.lang);
  if (docKey) void loadCatalogue(docKey);
}

/** The text for ``key``: the page's language, else English, else the key; a ``count`` picks the
 *  plural form by the language's own rules; ``{name}`` is filled from ``params``. */
export function makeT(messages: Flat, locale: string): PageCatalogue['t'] {
  return (key, params) => {
    let text = messages[key] ?? english[key] ?? key;
    if (typeof params?.count === 'number') {
      const form = new Intl.PluralRules(locale).select(params.count);
      text =
        messages[`${key}_${form}`] ??
        (messages[key] === undefined ? english[`${key}_${form}`] : undefined) ??
        messages[`${key}_other`] ??
        text;
    }
    return params
      ? text.replace(/\{(\w+)\}/g, (whole, name: string) =>
          name in params ? String(params[name]) : whole,
        )
      : text;
  };
}

function Provide({
  locale,
  messages,
  children,
}: {
  locale: string;
  messages: Flat;
  children: ReactNode;
}) {
  const value = useMemo(() => ({ locale, t: makeT(messages, locale) }), [locale, messages]);
  return <PageCatalogueContext.Provider value={value}>{children}</PageCatalogueContext.Provider>;
}

function Lazy({
  locale,
  loaderKey,
  children,
}: {
  locale: string;
  loaderKey: string;
  children: ReactNode;
}) {
  // Always invoke `use` on the cached promise instance so React 19 never sees a conditional `use()`.
  const messages = use(loadCatalogue(loaderKey));
  return (
    <Provide locale={locale} messages={messages}>
      {children}
    </Provide>
  );
}

export function PageLocale({ locale, children }: { locale: string; children: ReactNode }) {
  const key = resolveLoaderKey(locale);
  if (!key) {
    return (
      <Provide locale={locale} messages={{}}>
        {children}
      </Provide>
    );
  }
  const cached = loaded.get(key);
  if (cached) {
    return (
      <Provide locale={locale} messages={cached}>
        {children}
      </Provide>
    );
  }
  return (
    <Suspense fallback={null}>
      <Lazy locale={locale} loaderKey={key}>
        {children}
      </Lazy>
    </Suspense>
  );
}
