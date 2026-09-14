/**
 * This module's half of the framework's i18n convention.
 *
 * The framework generates `keys` and the `t()` key union into
 * `@simple-module-py/i18n` from the *merged* registry of every locale
 * directory a host loads — but it writes them into `packages/i18n/src`, which
 * only exists inside the framework's own monorepo. A module published from
 * anywhere else is therefore absent from the published package's key union:
 * `keys.news` does not exist, and `t('news.x')` is a type error. That is a
 * property of where the generator writes, not of anything news does wrong, so
 * the module derives its own two pieces here instead:
 *
 * - `keys`, the same nested tree of dotted keys, derived from this module's
 *   own `locales/en.json` at compile time. Nothing is generated and nothing
 *   can drift: the shape *is* the catalogue's, so a key that is not in the
 *   JSON is a type error at the call site, and `tsc` is what catches the
 *   missing-key failure the framework's generator catches upstream.
 * - `useT`, which resolves against the same i18next instance the host
 *   configured, supplying the English text as the `defaultValue` the
 *   published overloads demand of a `string` key — so a missing translation
 *   renders as English rather than as the key.
 *
 * The namespace prefix (`news.`) is the one `NewsModule.locale_dirs()`
 * registers the catalogue under, so a leaf here is the exact flat key the
 * host ships in the `i18n` shared prop.
 */

import { t as frameworkT, useT as useFrameworkT } from '@simple-module-py/i18n';
import { useMemo } from 'react';

import en from '../locales/en.json';

/** The namespace `NewsModule.locale_dirs()` registers `locales/` under. */
const NAMESPACE = 'news';

/** CLDR plural categories, in spec order — the framework's `PLURAL_CATEGORIES`. */
const PLURAL_SUFFIXES = ['_zero', '_one', '_two', '_few', '_many', '_other'] as const;

type PluralCategory = 'zero' | 'one' | 'two' | 'few' | 'many' | 'other';

/** `count_one` / `count_other` -> `count`, the stem `t(key, {count})` takes. */
type StemOf<K extends string> = K extends `${infer S}_${PluralCategory}` ? S : never;

/**
 * The catalogue's shape with every leaf replaced by its dotted key.
 *
 * Leaves are `string` rather than the literal, deliberately: the published
 * `t()` narrows its key to the framework's own union, and a literal outside
 * that union is rejected where a widened `string` is accepted.
 */
type KeyTree<T> = {
  [K in keyof T]: T[K] extends string ? string : KeyTree<T[K]>;
} & { [K in StemOf<Extract<keyof T, string>>]: string };

function build(node: Record<string, unknown>, prefix: string): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [name, value] of Object.entries(node)) {
    const path = `${prefix}.${name}`;
    if (typeof value !== 'string') {
      out[name] = build(value as Record<string, unknown>, path);
      continue;
    }
    out[name] = path;
    // A plural entry also publishes its stem, which is what call sites pass:
    // i18next appends the category itself once `count` is in the params.
    const suffix = PLURAL_SUFFIXES.find((s) => name.endsWith(s));
    if (suffix) {
      const stem = name.slice(0, -suffix.length);
      if (!(stem in out)) out[stem] = `${prefix}.${stem}`;
    }
  }
  return out;
}

/**
 * Every key this module's catalogue defines, as `keys.news.<section>.<name>`.
 *
 * Namespaced one level deep even though only news is in here, so a call site
 * reads exactly as it does in a framework module — `t(keys.news.list.title)`
 * — and moving one there later is an import change and nothing else.
 */
export const keys: Record<typeof NAMESPACE, KeyTree<typeof en>> = {
  [NAMESPACE]: build(en, NAMESPACE) as KeyTree<typeof en>,
};

function flatten(node: Record<string, unknown>, prefix: string, out: Record<string, string>) {
  for (const [name, value] of Object.entries(node)) {
    const path = `${prefix}.${name}`;
    if (typeof value !== 'string') {
      flatten(value as Record<string, unknown>, path, out);
      continue;
    }
    out[path] = value;
    // A plural entry also answers for its stem, which is what call sites pass
    // — the same rule `build()` applies to `keys`, and it has to stay the same
    // rule: a stem `keys` publishes that `english` does not know falls back to
    // the dotted key, the very leak this map exists to close. `_other` wins
    // where several forms exist, being the one category every language has
    // and the right reading for an unknown count.
    const suffix = PLURAL_SUFFIXES.find((s) => name.endsWith(s));
    if (suffix) {
      const stem = `${prefix}.${name.slice(0, -suffix.length)}`;
      if (suffix === '_other' || !(stem in out)) out[stem] = value;
    }
  }
  return out;
}

/**
 * Every key's English text, flat, for the `defaultValue` a miss falls back to.
 *
 * The framework's `configureI18n` sets `fallbackLng` to the *negotiated*
 * locale rather than to English, and this module ships only `en.json` — so a
 * reader negotiated into any other configured console language would see raw
 * dotted keys wherever a catalogue entry is missing, which is everywhere. The
 * public archive is what that would land on. Handing i18next the English as
 * the default restores exactly what the hardcoded strings did before the
 * catalogue existed: English, whatever the locale, until a translation
 * arrives. The catalogue is already in memory for `keys`; this is the same
 * data read the other way.
 */
const english: Record<string, string> = flatten(en, NAMESPACE, {});

/** Interpolation values — `{name}` placeholders, and `count` for plurals. */
export type TranslateParams = Record<string, unknown>;

/** What every call site in this module translates with. */
export type Translate = (key: string, params?: TranslateParams) => string;

/**
 * `t()` for code that runs outside React — the API client's error decoder is
 * the only caller.
 *
 * Resolved at call time against the shared i18next instance, so it reads the
 * language in force when the message is produced. That is what makes it safe
 * here and unsafe in a schema or a config object built at import time, which
 * would freeze against whatever was loaded first.
 */
export function translate(key: string, params?: TranslateParams): string {
  return frameworkT(key, { defaultValue: english[key] ?? key, ...params });
}

/**
 * `t()` for this module's keys.
 *
 * The published `t()` accepts a `string` key only alongside a `defaultValue`,
 * because a key outside its generated union might not resolve. The default is
 * the English text — see `english` above for why it is not the key itself.
 */
export function useT(): { t: Translate } {
  const { t } = useFrameworkT();
  return useMemo(
    () => ({
      t: (key: string, params?: TranslateParams) =>
        t(key, { defaultValue: english[key] ?? key, ...params }),
    }),
    [t],
  );
}
