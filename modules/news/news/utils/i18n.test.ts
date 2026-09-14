import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import i18next from 'i18next';
import { describe, expect, it } from 'vitest';

import en from '../locales/en.json';
import { keys, translate } from './i18n';

/**
 * The catalogue and the call sites, checked against each other.
 *
 * `tsc` already rejects a key that is not in `en.json` — the key tree is
 * derived from the JSON, so a typo is a missing property. What it cannot see
 * is the other three ways this breaks:
 *
 *  - an entry nobody references any more, which a translator still pays to
 *    translate;
 *  - a plural entry missing one of its CLDR forms, which renders as the raw
 *    stem the moment a count lands on the missing category;
 *  - a `{placeholder}` that no call site fills, which reaches a reader as
 *    literal braces.
 */

const NEWS = join(import.meta.dirname, '..');
const PLURAL_SUFFIXES = ['_zero', '_one', '_two', '_few', '_many', '_other'];

function sources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      sources(path, out);
    } else if (/\.tsx?$/.test(name) && !name.endsWith('i18n.ts')) {
      out.push(path);
    }
  }
  return out;
}

/** Every `news.`-prefixed key path the module's own code reaches for.
 *
 * Two shapes, because call sites alias a section (`const copy =
 * keys.news.seo;`) rather than repeating the prefix on every line. */
function referencedKeys(): Set<string> {
  const found = new Set<string>();
  for (const path of sources(NEWS)) {
    const text = readFileSync(path, 'utf-8');
    for (const match of text.matchAll(/\bkeys\.news((?:\.\w+)+)/g)) {
      found.add(match[1].slice(1));
    }
    for (const alias of text.matchAll(/\b(?:const|let)\s+(\w+)\s*=\s*keys\.news\.(\w+);/g)) {
      const [, name, section] = alias;
      for (const use of text.matchAll(new RegExp(`\\b${name}\\.(\\w+)`, 'g'))) {
        found.add(`${section}.${use[1]}`);
      }
    }
  }
  return found;
}

function flatten(node: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(node).flatMap(([name, value]) => {
    const key = prefix ? `${prefix}.${name}` : name;
    return typeof value === 'string' ? [key] : flatten(value as Record<string, unknown>, key);
  });
}

/** `list.across_statuses_one` -> `list.across_statuses`, else the key itself. */
function stem(key: string): string {
  const suffix = PLURAL_SUFFIXES.find((s) => key.endsWith(s));
  return suffix ? key.slice(0, -suffix.length) : key;
}

const CATALOGUE = flatten(en as unknown as Record<string, unknown>);

describe('the news catalogue', () => {
  it('is reachable through the key tree at every leaf', () => {
    for (const key of CATALOGUE) {
      const leaf = key
        .split('.')
        .reduce<unknown>((node, part) => (node as Record<string, unknown>)?.[part], keys.news);
      expect(leaf, key).toBe(`news.${key}`);
    }
  });

  it('has no entry the module stopped using', () => {
    // A plural entry is reached through its stem, which is what `t(key,
    // {count})` takes — `_one` is never named at a call site.
    const referenced = referencedKeys();
    const orphans = CATALOGUE.filter((key) => !referenced.has(stem(key)));
    expect(orphans).toEqual([]);
  });

  it('gives every plural entry both English forms', () => {
    // English needs `one` and `other`. A stem with only one of them renders
    // as the raw key for every count that lands on the missing category.
    const stems = new Set(CATALOGUE.filter((key) => key !== stem(key)).map(stem));
    for (const base of stems) {
      expect(CATALOGUE, base).toContain(`${base}_one`);
      expect(CATALOGUE, base).toContain(`${base}_other`);
    }
  });

  it('fills every placeholder it declares', () => {
    // Each `{name}` has to be supplied by whichever call site passes the key,
    // so the union of every object literal in the module has to cover it.
    const params = new Set<string>();
    for (const path of sources(NEWS)) {
      const text = readFileSync(path, 'utf-8');
      for (const match of text.matchAll(/(\w+):/g)) params.add(match[1]);
      // Shorthand properties too — `{ tag }` is how most of them are passed.
      for (const match of text.matchAll(/[{,]\s*(\w+)\s*[,}]/g)) params.add(match[1]);
    }
    const declared = new Set<string>();
    for (const value of Object.values(flattenValues(en as unknown as Record<string, unknown>))) {
      for (const match of value.matchAll(/\{(\w+)\}/g)) declared.add(match[1]);
    }
    expect([...declared].filter((name) => !params.has(name))).toEqual([]);
  });
});

function flattenValues(node: Record<string, unknown>, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, value] of Object.entries(node)) {
    const key = prefix ? `${prefix}.${name}` : name;
    if (typeof value === 'string') out[key] = value;
    else Object.assign(out, flattenValues(value as Record<string, unknown>, key));
  }
  return out;
}

describe('a missing translation', () => {
  it('renders English, not the key', async () => {
    // The framework inits i18next with `fallbackLng` set to the negotiated
    // locale, never to English — so on a host whose console speaks German, a
    // reader lands on a catalogue this module does not ship, and every miss
    // would render as its dotted key. The harness here happens to init with
    // `en`, which would mask exactly that: pull the English bundle out so the
    // miss is a real one, and the only thing standing between the reader and
    // `news.list.title` is the default the wrapper supplies.
    const bundle = i18next.getResourceBundle('en', 'translation');
    i18next.removeResourceBundle('en', 'translation');
    await i18next.changeLanguage('de');
    try {
      expect(translate(keys.news.list.title)).toBe('News');
      expect(translate(keys.news.list.title)).not.toContain('.');
    } finally {
      i18next.addResourceBundle('en', 'translation', bundle, true, true);
      await i18next.changeLanguage('en');
    }
  });
});
