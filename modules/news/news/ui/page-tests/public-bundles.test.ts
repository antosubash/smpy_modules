import { build } from 'vite';
import { expect, it } from 'vitest';

it('builds standalone public news entries without resolving optional pagebuilder', async () => {
  const result = await build({
    configFile: false,
    logLevel: 'silent',
    build: {
      write: false,
      rolldownOptions: {
        preserveEntrySignatures: 'strict',
        input: [
          'modules/news/news/index.ts',
          'modules/news/news/pages/PublicArticle.tsx',
          'modules/news/news/pages/PublicIndex.tsx',
        ],
        external(id) {
          if (id.startsWith('@simple-module-py/pagebuilder')) {
            throw new Error('Standalone news must not resolve pagebuilder');
          }
          return !id.startsWith('.') && !id.startsWith('/');
        },
      },
    },
  });
  if (!('output' in result)) throw new Error('Expected an in-memory bundle');
  expect(result.output.filter((output) => output.type === 'chunk' && output.isEntry)).toHaveLength(
    3,
  );
});

it("keeps the shared layout palette out of pagebuilder's static entry graph", async () => {
  const result = await build({
    configFile: false,
    logLevel: 'silent',
    build: {
      write: false,
      rolldownOptions: {
        preserveEntrySignatures: 'strict',
        input: 'modules/pagebuilder/pagebuilder/index.ts',
        external: (id) => !id.startsWith('.') && !id.startsWith('/'),
      },
    },
  });
  if (!('output' in result)) throw new Error('Expected an in-memory bundle');
  const outputs = result.output.filter((output) => output.type === 'chunk');
  const entry = outputs.find((output) => output.isEntry);
  expect(entry).toBeDefined();
  const visited = new Set<string>();
  function visit(path: string) {
    if (visited.has(path)) return;
    visited.add(path);
    const output = outputs.find((chunk) => chunk.fileName === path);
    if (!output) return; // external package
    for (const input of Object.keys(output.modules)) {
      expect(input).not.toMatch(/\/puckConfig\.tsx$|\/editor\/|\/pages\//);
    }
    for (const imported of output.imports) visit(imported);
  }
  visit(entry?.fileName as string);
});
