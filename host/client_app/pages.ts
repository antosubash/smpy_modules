/**
 * Inertia page resolver.
 *
 * Module pages are discovered via a generated file (modules.generated.ts)
 * emitted by the Python host at boot, or manually via `smpy gen-pages`. Each
 * installed module contributes an import.meta.glob() call with an absolute
 * path, so pages shipped inside pip-installed module wheels resolve.
 *
 * Host-level pages live in client_app/pages/{PageName}.tsx and are
 * registered under just "{PageName}" (e.g. "Error").
 */

import { moduleGlobs } from './modules.generated';

type PageModule = { default: React.ComponentType<Record<string, unknown>> };
type PageLoader = () => Promise<PageModule>;

const hostPages = import.meta.glob<PageModule>('./pages/**/*.tsx');

const pages: Record<string, PageLoader> = {};

for (const [moduleName, globEntries] of Object.entries(moduleGlobs)) {
  for (const [filePath, loader] of Object.entries(globEntries)) {
    const match = filePath.match(/\/pages\/(.+)\.tsx$/);
    if (match) {
      pages[`${moduleName}/${match[1]}`] = loader;
    }
  }
}

for (const [filePath, loader] of Object.entries(hostPages)) {
  const match = filePath.match(/\.\/pages\/(.+)\.tsx$/);
  if (match) {
    pages[match[1]] = loader;
  }
}

export async function resolvePage(
  name: string,
): Promise<React.ComponentType<Record<string, unknown>>> {
  const loader = pages[name];
  if (!loader) {
    throw new Error(`Page "${name}" not found. Available pages: ${Object.keys(pages).join(', ')}`);
  }
  const module = await loader();
  return module.default;
}
