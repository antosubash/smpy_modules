import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import i18next from 'i18next';
import { describe, expect, it } from 'vitest';

import en from '../locales/en.json';
import { keys, translate } from './i18n';

/** The catalogue and the call sites, checked against each other. */

const AI = join(import.meta.dirname, '..');

function sources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) sources(path, out);
    else if (/\.tsx?$/.test(name) && !/i18n(\.test)?\.ts$/.test(name)) out.push(path);
  }
  return out;
}

function flatten(node: Record<string, unknown>, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, value] of Object.entries(node)) {
    const key = prefix ? `${prefix}.${name}` : name;
    if (typeof value === 'string') out[key] = value;
    else Object.assign(out, flatten(value as Record<string, unknown>, key));
  }
  return out;
}

const CATALOGUE = flatten(en as unknown as Record<string, unknown>);
const SOURCE = sources(AI)
  .map((p) => readFileSync(p, 'utf-8'))
  .join('\n');

describe('the ai catalogue', () => {
  it('is reachable through the key tree at every leaf', () => {
    for (const key of Object.keys(CATALOGUE)) {
      const leaf = key
        .split('.')
        .reduce<unknown>((node, part) => (node as Record<string, unknown>)?.[part], keys.ai);
      expect(leaf, key).toBe(`ai.${key}`);
    }
  });

  it('has no entry the module stopped using', () => {
    // Call sites alias a section (`const c = keys.ai.card;`) as well as
    // spelling the full path, so match either `keys.ai.<s>.<n>` or `.<n>`
    // reached through the section alias.
    const orphans = Object.keys(CATALOGUE).filter((key) => {
      const [section, name] = key.split('.');
      return !(
        SOURCE.includes(`keys.ai.${key}`) ||
        (SOURCE.includes(`keys.ai.${section};`) && new RegExp(`\\b\\w+\\.${name}\\b`).test(SOURCE))
      );
    });
    expect(orphans).toEqual([]);
  });

  it('fills every placeholder it declares', () => {
    const missing: string[] = [];
    for (const value of Object.values(CATALOGUE)) {
      for (const match of value.matchAll(/\{(\w+)\}/g)) {
        if (!new RegExp(`\\b${match[1]}\\b`).test(SOURCE)) missing.push(match[1]);
      }
    }
    expect(missing).toEqual([]);
  });
});

describe('a missing translation', () => {
  it('renders English, not the key', async () => {
    // Pull the English bundle out so the miss is real: only the wrapper's
    // `defaultValue` then stands between the reader and the dotted key.
    const bundle = i18next.getResourceBundle('en', 'translation');
    i18next.removeResourceBundle('en', 'translation');
    await i18next.changeLanguage('de');
    try {
      expect(translate(keys.ai.settings.save)).toBe('Save');
    } finally {
      i18next.addResourceBundle('en', 'translation', bundle, true, true);
      await i18next.changeLanguage('en');
    }
  });
});
