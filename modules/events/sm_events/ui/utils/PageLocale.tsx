import { type ReactNode, Suspense, use, useMemo } from 'react';
import { english, flatten } from './i18n';
import { type PageCatalogue, PageCatalogueContext } from './pageLocale';

/**
 * Public pages speak the language of the page, not of the visitor's console.
 *
 * The server picks the page's language from its address (`/de/events/...`) and sends it as the
 * `locale` prop, but the framework's i18n props follow the cookie or `Accept-Language`, so a German
 * event page opened by an English browser would otherwise carry English headings. Inside this
 * provider `useT` reads the module's own catalogue for the page's language: English is in the
 * bundle, every other language is one lazy chunk named in `loaders` (an explicit map, so the
 * bundler emits a chunk per language), and a language without one reads English.
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

/** Start loading a language's catalogue (the pages do it on first render; tests do it up front). */
export function loadCatalogue(locale: string): Promise<Flat> {
  const key = resolveLoaderKey(locale);
  const cacheKey = key ?? locale;
  const hit = pending.get(cacheKey);
  if (hit) return hit;
  const loader = key ? loaders[key] : undefined;
  const promise = (loader ? loader() : Promise.resolve({ default: {} }))
    .then((m) => {
      const flat = flatten(m.default as Record<string, unknown>, 'events', {});
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

// Preload the page's catalogue as soon as this module runs so the chunk starts fetching before
// React mounts (the server writes `<html lang>` on public pages).
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
      // English is the floor for a form the page's language lacks (an English page has no
      // catalogue of its own, so its `_one` comes from `english`).
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
  // Always invoke `use` on the cached promise instance so React 19 never sees a conditional `use()`
  // between the suspended render and the resumed render.
  const messages = use(loadCatalogue(loaderKey));
  return (
    <Provide locale={locale} messages={messages}>
      {children}
    </Provide>
  );
}

export function PageLocale({ locale, children }: { locale: string; children: ReactNode }) {
  const key = resolveLoaderKey(locale);
  // No chunk to wait for: English and a language without a catalogue render at once.
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
