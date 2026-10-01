import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

import catalog from '../../locales/en.json';

/**
 * Every `t('records.…')` the media picker renders is in the catalog, with the
 * catalog's own text as its fallback — otherwise a translated install shows
 * the English default for a key nobody can translate, and the two copies of
 * a sentence drift apart the first time one is edited.
 */
const here = dirname(fileURLToPath(import.meta.url));
const sources = [
  ...readdirSync(here)
    .filter((name) => name.endsWith('.tsx') && !name.includes('.test.'))
    .map((name) => join(here, name)),
  join(here, '..', 'fields', 'MediaField.tsx'),
];
const CALL =
  /t\(\s*'(records\.[a-z_.]+)',\s*\{\s*defaultValue:\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")/g;

function lookup(key: string): unknown {
  return key
    .split('.')
    .slice(1)
    .reduce<unknown>(
      (node, part) => (node as Record<string, unknown> | undefined)?.[part],
      catalog,
    );
}

describe('the media picker catalog', () => {
  const calls = sources.flatMap((file) =>
    Array.from(readFileSync(file, 'utf8').matchAll(CALL), (m) => ({
      key: m[1],
      fallback: m[2] ?? m[3],
    })),
  );

  it('finds the calls it checks', () => {
    expect(calls.length).toBeGreaterThan(25);
  });

  it.each(calls)('$key is in en.json with the same text', ({ key, fallback }) => {
    expect(lookup(key)).toBe(fallback);
  });
});
