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

function load(locale: string): Promise<Flat> {
  const hit = pending.get(locale);
  if (hit) return hit;
  const loader = loaders[locale];
  const promise = (loader ? loader() : Promise.resolve({ default: {} })).then((m) => {
    const flat = flatten(m.default as Record<string, unknown>, 'events', {});
    loaded.set(locale, flat);
    return flat;
  });
  pending.set(locale, promise);
  return promise;
}

/** The text for ``key``: the page's language, else English, else the key; a ``count`` picks the
 *  plural form by the language's own rules; ``{name}`` is filled from ``params``. */
export function makeT(messages: Flat, locale: string): PageCatalogue['t'] {
  return (key, params) => {
    let text = messages[key] ?? english[key] ?? key;
    if (typeof params?.count === 'number') {
      const form = new Intl.PluralRules(locale).select(params.count);
      text = messages[`${key}_${form}`] ?? messages[`${key}_other`] ?? text;
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

function Lazy({ locale, children }: { locale: string; children: ReactNode }) {
  const messages = loaded.get(locale) ?? use(load(locale));
  return (
    <Provide locale={locale} messages={messages}>
      {children}
    </Provide>
  );
}

export function PageLocale({ locale, children }: { locale: string; children: ReactNode }) {
  // No chunk to wait for: English and a language without a catalogue render at once.
  if (!loaders[locale]) {
    return (
      <Provide locale={locale} messages={{}}>
        {children}
      </Provide>
    );
  }
  return (
    <Suspense fallback={null}>
      <Lazy locale={locale}>{children}</Lazy>
    </Suspense>
  );
}
