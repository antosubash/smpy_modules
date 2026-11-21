import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/** A host without the events module never bundles `events-extensions.ts` (events' own guarded glob
 *  is its only importer), so nothing records ships may reach it, or the `@simple-module-py/events`
 *  import it makes, from the entry points a host does load: the pages (a glob in the host) and
 *  `pagebuilder-blocks.ts`. */
const ROOT = resolve(__dirname, '../..');
const EXTENSIONS = join(ROOT, 'events-extensions.ts');
const IMPORT = /(?:from|import)\s*\(?\s*['"]([^'"]+)['"]/g;
const SUFFIXES = ['', '.ts', '.tsx', '/index.ts', '/index.tsx'];

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules' || name === '__pycache__') continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.(ts|tsx)$/.test(name)) out.push(full);
  }
  return out;
}

function resolveImport(from: string, spec: string): string | null {
  if (!spec.startsWith('.')) return null;
  const base = resolve(dirname(from), spec);
  for (const suffix of SUFFIXES) {
    try {
      if (statSync(base + suffix).isFile()) return base + suffix;
    } catch {}
  }
  return null;
}

function reachable(entries: string[]): Map<string, string[]> {
  const seen = new Map<string, string[]>();
  const queue = [...entries];
  while (queue.length) {
    const file = queue.pop() as string;
    if (seen.has(file)) continue;
    const specs = [...readFileSync(file, 'utf8').matchAll(IMPORT)].map((m) => m[1]);
    seen.set(file, specs);
    for (const spec of specs) {
      const next = resolveImport(file, spec);
      if (next) queue.push(next);
    }
  }
  return seen;
}

describe('records without events', () => {
  const entries = [join(ROOT, 'pagebuilder-blocks.ts'), ...walk(join(ROOT, 'pages'))];
  const graph = reachable(entries);

  it('has entry points to start from', () => {
    expect(entries.length).toBeGreaterThan(3);
    expect(graph.size).toBeGreaterThan(entries.length);
  });

  it('never reaches the events extension file or the events screens', () => {
    const files = [...graph.keys()].map((f) => relative(ROOT, f));
    expect(files).not.toContain('events-extensions.ts');
    expect(files.filter((f) => f.startsWith('ui/events/'))).toEqual([]);
  });

  it('never reaches an import of the events package', () => {
    const importers = [...graph.entries()]
      .filter(([, specs]) => specs.some((s) => s.startsWith('@simple-module-py/events')))
      .map(([f]) => relative(ROOT, f));
    expect(importers).toEqual([]);
  });

  it('keeps the events import to the extension file and its screens', () => {
    const importers = walk(ROOT)
      .filter((f) => !f.endsWith('.test.ts') && !f.endsWith('.test.tsx'))
      .filter((f) => /@simple-module-py\/events/.test(readFileSync(f, 'utf8')))
      .map((f) => relative(ROOT, f))
      .sort();
    expect(importers).toEqual([
      'events-extensions.ts',
      'ui/events/RecordDateDetail.tsx',
      'ui/events/RecordDatesSettings.tsx',
    ]);
    expect(EXTENSIONS).toContain('events-extensions.ts');
  });

  it('declares the events package as an optional peer', () => {
    const pkg = JSON.parse(readFileSync(resolve(ROOT, '../package.json'), 'utf8'));
    expect(pkg.peerDependencies['@simple-module-py/events']).toBeDefined();
    expect(pkg.peerDependenciesMeta['@simple-module-py/events'].optional).toBe(true);
  });
});
