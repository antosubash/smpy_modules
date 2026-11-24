import { fileURLToPath } from 'node:url';
import { build } from 'vite';
import { expect, it } from 'vitest';

const entry = fileURLToPath(new URL('../../../pagebuilder-blocks.ts', import.meta.url));
const pagebuilder = fileURLToPath(
  new URL('../../../../../pagebuilder/pagebuilder/index.ts', import.meta.url),
);
const gallery = '/ui/fields/file-picker/file-gallery.tsx';

it('keeps the registered media gallery behind a dynamic import', async () => {
  const result = await build({
    configFile: false,
    logLevel: 'error',
    plugins: [
      {
        name: 'isolate-new-media-picker-imports',
        enforce: 'pre',
        resolveId(source) {
          if (source === '@simple-module-py/pagebuilder') return pagebuilder;
          // Existing createImageField / StatsView paths already reach the gallery.
          // Exclude those two legacy paths to guard only the new registration/export.
          if (/\/(image-picker-field|stats-widget)(\.tsx)?$/.test(source)) {
            return { id: source, external: true };
          }
          if (!source.startsWith('.') && !source.startsWith('/')) {
            return { id: source, external: true };
          }
        },
      },
    ],
    build: {
      write: false,
      minify: false,
      rollupOptions: { input: entry },
    },
  });
  if (!('output' in result)) throw new Error('Expected a single bundle output');
  const chunks = result.output.filter((output) => output.type === 'chunk');
  const main = chunks.find((chunk) => chunk.isEntry);
  expect(main).toBeDefined();
  const galleryChunk = chunks.find((chunk) =>
    Object.keys(chunk.modules).some((id) => id.endsWith(gallery)),
  );
  expect(galleryChunk).toBeDefined();

  function reachable(dynamic: boolean): Set<string> {
    const seen = new Set<string>();
    const pending = [main?.fileName ?? ''];
    while (pending.length) {
      const name = pending.pop() as string;
      if (seen.has(name)) continue;
      seen.add(name);
      const chunk = chunks.find((item) => item.fileName === name);
      if (chunk) pending.push(...chunk.imports, ...(dynamic ? chunk.dynamicImports : []));
    }
    return seen;
  }

  expect(
    reachable(false).has(galleryChunk?.fileName ?? ''),
    Object.keys(main?.modules ?? {}).join('\n'),
  ).toBe(false);
  expect(reachable(true).has(galleryChunk?.fileName ?? '')).toBe(true);
});
