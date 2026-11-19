import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '../../../../..');
const NAME = 'events-extensions.ts';

function find(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === '.venv' || entry === '.claude') continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) find(path, out);
    else if (entry === NAME) out.push(path);
  }
  return out;
}

const files = find(join(REPO, 'modules'));
const IMPORT = /^\s*import\s+(type\s+)?[^;]*?from\s+['"]([^'"]+)['"]/gm;

/** What the glob would pick up: no test or support file may carry the name. */
describe('plugin files', () => {
  it('only the registration file carries the name, in a package root', () => {
    for (const file of files) {
      const rel = relative(join(REPO, 'modules'), file).split('/');
      expect(rel).toHaveLength(3); // <dist>/<package>/events-extensions.ts
    }
  });

  it('import only the events package (or types), and load components lazily', () => {
    for (const file of files) {
      const text = readFileSync(file, 'utf8');
      for (const [, isType, from] of text.matchAll(IMPORT)) {
        if (isType) continue;
        expect(from, file).toBe('@simple-module-py/events');
      }
      // every component is handed over as `() => import(...)`, never a static reference
      expect(text, file).not.toMatch(
        /\b(Chip|Detail|EditorSection|SettingsSection|PublicDetail|Component):\s*[A-Z]\w*\s*[,}]/,
      );
    }
  });

  it('events itself ships none in a stray place', () => {
    expect(files.every((f) => !f.includes('/ui/') && !f.includes('/pages/'))).toBe(true);
  });
});
