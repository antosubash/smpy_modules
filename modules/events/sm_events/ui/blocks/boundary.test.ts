import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '../..'); // sm_events
const PAGEBUILDER = /['"]@simple-module-py\/pagebuilder['"]/;
const FROM = /(?:from|import)\s+['"](\.[^'"]+)['"]/g;

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name !== 'node_modules' && name !== 'static') walk(path, out);
    } else if (/\.(ts|tsx)$/.test(name)) out.push(path);
  }
  return out;
}

function resolveFile(from: string, spec: string): string | null {
  const base = resolve(dirname(from), spec);
  for (const candidate of [`${base}.tsx`, `${base}.ts`, `${base}/index.tsx`, `${base}/index.ts`]) {
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

/** Everything a file reaches through static relative imports (an `import()` is a chunk of its own
 *  and is not followed). */
function reach(entry: string): Set<string> {
  const seen = new Set<string>();
  const queue = [entry];
  while (queue.length > 0) {
    const file = queue.pop() as string;
    if (seen.has(file)) continue;
    seen.add(file);
    const source = readFileSync(file, 'utf8').replace(/import\((['"])[^'"]+\1\)/g, '');
    for (const [, spec] of source.matchAll(FROM)) {
      const next = resolveFile(file, spec as string);
      if (next) queue.push(next);
    }
  }
  return seen;
}

const rel = (file: string) => relative(ROOT, file);

describe('the pagebuilder boundary', () => {
  it('only pagebuilder-blocks.ts and ui/blocks import @simple-module-py/pagebuilder', () => {
    const offenders = walk(ROOT)
      .filter((file) => PAGEBUILDER.test(readFileSync(file, 'utf8')))
      .map(rel)
      .filter((file) => file !== 'pagebuilder-blocks.ts' && !file.startsWith('ui/blocks/'));
    expect(offenders).toEqual([]);
  });

  it('index.ts never reaches ui/blocks, so a host without pagebuilder never needs it', () => {
    const reached = [...reach(resolve(ROOT, 'index.ts'))].map(rel);
    expect(reached.filter((file) => file.startsWith('ui/blocks/'))).toEqual([]);
    expect(reached).not.toContain('pagebuilder-blocks.ts');
  });

  it('the registration graph is lazy for the calendar', () => {
    const entry = resolve(ROOT, 'pagebuilder-blocks.ts');
    if (!existsSync(entry)) return; // written in the registration task
    const files = [...reach(entry)];
    const calendar = files.map(rel).filter((file) => file.startsWith('ui/calendar/'));
    expect(calendar).toEqual([]);
    const fullcalendar = files.filter((file) =>
      /@fullcalendar|@full-ui/.test(readFileSync(file, 'utf8')),
    );
    expect(fullcalendar.map(rel)).toEqual([]);
  });

  it('the blocks reach no console code', () => {
    const entry = resolve(ROOT, 'pagebuilder-blocks.ts');
    if (!existsSync(entry)) return;
    const consoleCode = [...reach(entry)]
      .map(rel)
      .filter((file) =>
        /^ui\/components\/(editor|calendars|share|feeds|events|categories|import)\/|^ui\/calendar\/console\/|^ui\/hooks\/use(Event|Events|EventActions|Calendars|Shares|FeedTokens|Candidates|Categories)\.|SourcesDialog|TypeSection/.test(
          file,
        ),
      );
    expect(consoleCode).toEqual([]);
  });
});
