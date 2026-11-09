import { t as frameworkT, useT as useFrameworkT } from '@simple-module-py/i18n';
import { useMemo } from 'react';

import en from '../../locales/en.json';

const NAMESPACE = 'analytics';

const PLURAL_SUFFIXES = ['_zero', '_one', '_two', '_few', '_many', '_other'] as const;

type PluralCategory = 'zero' | 'one' | 'two' | 'few' | 'many' | 'other';

type StemOf<K extends string> = K extends `${infer S}_${PluralCategory}` ? S : never;

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
    const suffix = PLURAL_SUFFIXES.find((s) => name.endsWith(s));
    if (suffix) {
      const stem = name.slice(0, -suffix.length);
      if (!(stem in out)) out[stem] = `${prefix}.${stem}`;
    }
  }
  return out;
}

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
    const suffix = PLURAL_SUFFIXES.find((s) => name.endsWith(s));
    if (suffix) {
      const bareStem = name.slice(0, -suffix.length);
      const stem = `${prefix}.${bareStem}`;
      if (stem in out) continue;
      const other = node[`${bareStem}_other`];
      if (typeof other === 'string') {
        out[stem] = other;
      } else {
        out[stem] = PLURAL_SUFFIXES.map((s) => node[`${bareStem}${s}`]).find(
          (v): v is string => typeof v === 'string',
        ) as string;
      }
    }
  }
  return out;
}

const english: Record<string, string> = flatten(en, NAMESPACE, {});

export type TranslateParams = Record<string, unknown>;

export type Translate = (key: string, params?: TranslateParams) => string;

export function translate(key: string, params?: TranslateParams): string {
  return frameworkT(key, { defaultValue: english[key] ?? key, ...params });
}

export function useT(): { t: Translate; locale: string | undefined } {
  const { t, i18n } = useFrameworkT();
  // The console's language, for `Intl` date and number formatting: the
  // browser's own locale is not the one the console speaks (#189).
  const locale = i18n?.language || undefined;
  return useMemo(
    () => ({
      t: (key: string, params?: TranslateParams) =>
        t(key, { defaultValue: english[key] ?? key, ...params }),
      locale,
    }),
    [t, locale],
  );
}
