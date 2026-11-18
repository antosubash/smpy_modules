import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, it } from 'vitest';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const FROM = /(?:from|import)\s+['"](\.[^'"]+)['"]/g;

function resolveFile(from: string, spec: string): string | null {
  const base = resolve(dirname(from), spec);
  for (const candidate of [`${base}.tsx`, `${base}.ts`, `${base}/index.tsx`, `${base}/index.ts`]) {
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

/** Every file the public event page reaches through static relative imports (a lazy
 *  `import()` is a chunk of its own and is not followed here). */
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

it('the public event page never reaches console code', () => {
  const files = [...reach(resolve(ROOT, 'pages/PublicEvent.tsx'))].map((f) => f.slice(ROOT.length));
  const console = files.filter((f) =>
    /\/ui\/components\/(editor|calendars|share|feeds|events|categories)\/|\/ui\/calendar\/console\/|\/ui\/hooks\/use(Event|Events|EventActions|Calendars|Shares|FeedTokens|Candidates|Categories)\.|SourcesDialog|TypeSection/.test(
      f,
    ),
  );
  expect(console).toEqual([]);
});
