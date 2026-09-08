/**
 * This module's half of the framework's i18n convention.
 *
 * The framework generates `keys` and the `t()` key union into
 * `@simple-module-py/i18n` from the *merged* registry of every locale
 * directory a host loads — but it writes them into `packages/i18n/src`, which
 * only exists inside the framework's own monorepo. A module published from
 * anywhere else is therefore absent from the published package's key union:
 * `keys.pagebuilder` does not exist, and `t('pagebuilder.x')` is a type error.
 * That is a property of where the generator writes, not of anything
 * pagebuilder does wrong, so the module derives its own two pieces here
 * instead:
 *
 * - `keys`, the same nested tree of dotted keys, derived from this module's
 *   own `locales/en.json` at compile time. Nothing is generated and nothing
 *   can drift: the shape *is* the catalogue's, so a key that is not in the
 *   JSON is a type error at the call site, and `tsc` is what catches the
 *   missing-key failure the framework's generator catches upstream.
 * - `useT`, which resolves against the same i18next instance the host
 *   configured. It exists only to spell the `defaultValue` the published
 *   overloads demand of a `string` key; behaviour is i18next's own — a
 *   missing key renders as the key.
 *
 * The namespace prefix (`pagebuilder.`) is the one
 * `PagebuilderModule.locale_dirs()` registers the catalogue under, so a leaf
 * here is the exact flat key the host ships in the `i18n` shared prop.
 */

import { t as frameworkT, useT as useFrameworkT } from '@simple-module-py/i18n';
import { useMemo } from 'react';

import en from '../locales/en.json';

/** The namespace `PagebuilderModule.locale_dirs()` registers `locales/` under. */
const NAMESPACE = 'pagebuilder';

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
 * Every key this module's catalogue defines, as `keys.pagebuilder.<section>.<name>`.
 *
 * Namespaced one level deep even though only pagebuilder is in here, so a call
 * site reads exactly as it does in a framework module —
 * `t(keys.pagebuilder.pages.title)` — and moving one there later is an import
 * change and nothing else.
 */
export const keys: Record<typeof NAMESPACE, KeyTree<typeof en>> = {
  [NAMESPACE]: build(en, NAMESPACE) as KeyTree<typeof en>,
};

/** Interpolation values — `{name}` placeholders, and `count` for plurals. */
export type TranslateParams = Record<string, unknown>;

/** What every call site in this module translates with. */
export type Translate = (key: string, params?: TranslateParams) => string;

/**
 * `t()` for code that runs outside React — the API error decoders, and the
 * `getItemSummary` callbacks Puck invokes while rendering an array field.
 *
 * Resolved at call time against the shared i18next instance, so it reads the
 * language in force when the message is produced. That is what makes it safe
 * in a callback and unsafe in a schema or a config object built at import
 * time, which would freeze against whatever was loaded first.
 */
export function translate(key: string, params?: TranslateParams): string {
  return frameworkT(key, { defaultValue: key, ...params });
}

/**
 * `t()` for this module's keys.
 *
 * The published `t()` accepts a `string` key only alongside a `defaultValue`,
 * because a key outside its generated union might not resolve. Supplying the
 * key as its own default is what i18next already does on a miss, so this adds
 * a type, not a behaviour.
 */
export function useT(): { t: Translate } {
  const { t } = useFrameworkT();
  return useMemo(
    () => ({
      t: (key: string, params?: TranslateParams) => t(key, { defaultValue: key, ...params }),
    }),
    [t],
  );
}
