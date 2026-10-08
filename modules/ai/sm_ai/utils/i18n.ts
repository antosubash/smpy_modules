/**
 * This module's half of the framework's i18n convention.
 *
 * The framework generates `keys` and the `t()` key union into the published
 * `@simple-module-py/i18n` only for locale directories inside its own
 * monorepo, so `keys.ai` does not exist there and `t('ai.x')` is a type error.
 * The module therefore derives its own pieces — the same approach as the news
 * module (see `modules/news/news/utils/i18n.ts` for the long-form rationale):
 *
 * - `keys`, the nested tree of dotted keys, derived from `locales/en.json` at
 *   compile time, so a key the JSON lacks is a type error at the call site.
 * - `useT` / `translate`, which resolve against the host's i18next instance
 *   with the English text as `defaultValue`, so a missing translation renders
 *   English rather than the dotted key.
 *
 * The namespace prefix is the one `AiModule.locale_dirs()` registers.
 */

import { t as frameworkT, useT as useFrameworkT } from '@simple-module-py/i18n';
import { useMemo } from 'react';

import en from '../locales/en.json';

/** The namespace `AiModule.locale_dirs()` registers `locales/` under. */
const NAMESPACE = 'ai';

/** The catalogue's shape with every leaf typed `string` (see news for why). */
type KeyTree<T> = {
  [K in keyof T]: T[K] extends string ? string : KeyTree<T[K]>;
};

function build(node: Record<string, unknown>, prefix: string): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [name, value] of Object.entries(node)) {
    const path = `${prefix}.${name}`;
    out[name] = typeof value === 'string' ? path : build(value as Record<string, unknown>, path);
  }
  return out;
}

/** Every key this module's catalogue defines, as `keys.ai.<section>.<name>`. */
export const keys: Record<typeof NAMESPACE, KeyTree<typeof en>> = {
  [NAMESPACE]: build(en, NAMESPACE) as KeyTree<typeof en>,
};

function flatten(node: Record<string, unknown>, prefix: string, out: Record<string, string>) {
  for (const [name, value] of Object.entries(node)) {
    const path = `${prefix}.${name}`;
    if (typeof value === 'string') out[path] = value;
    else flatten(value as Record<string, unknown>, path, out);
  }
  return out;
}

/** Every key's English text — the `defaultValue` a missing translation uses. */
const english: Record<string, string> = flatten(en, NAMESPACE, {});

/** Interpolation values — `{name}` placeholders. */
export type TranslateParams = Record<string, unknown>;

/** What every call site in this module translates with. */
export type Translate = (key: string, params?: TranslateParams) => string;

/** `t()` for code that runs outside React (the API client's error decoder). */
export function translate(key: string, params?: TranslateParams): string {
  return frameworkT(key, { defaultValue: english[key] ?? key, ...params });
}

/** `t()` for this module's keys, English as the default. */
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
