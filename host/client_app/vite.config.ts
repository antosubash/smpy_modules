import fs from 'node:fs';
import path from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Force every importer (host, workspace module, wheel-installed module)
// to resolve to one React copy + a single Inertia hook context. Without
// dedupe, plugin-react fires "can't detect preamble" and `usePage` from
// a wheel-loaded page lands in a different React realm than the host's.
const REACT_CORE_DEPS = [
  'react',
  'react-dom',
  'react/jsx-runtime',
  'react/jsx-dev-runtime',
  '@inertiajs/react',
] as const;

// File-system serve root — the directory that holds `node_modules`. In flat
// mode that's the host root; in workspace mode npm hoists `node_modules` to
// the workspace root one level higher, so we walk up to find it.
function findNodeModulesRoot(start: string): string {
  let dir = start;
  while (dir !== path.dirname(dir)) {
    if (fs.existsSync(path.join(dir, 'node_modules'))) return dir;
    dir = path.dirname(dir);
  }
  return start;
}
const fsRoot = findNodeModulesRoot(__dirname);

// Load the module pages manifest written by the Python host at boot.
// Each entry points at an absolute pages/ directory — typically inside a
// pip-installed module wheel. Vite needs these in server.fs.allow so the
// dev server can read files outside the host root, and in
// optimizeDeps.entries so its dependency scanner discovers bare imports
// from wheel-installed pages and pre-bundles them.
//
// We also collect each module's package.json (one level up from pages/,
// where Hatch's force-include drops it) so the dependency walk in
// `collectOptimizeIncludes` reaches packages a wheel-installed page imports
// directly (`sonner`, `lucide-react`, ...). Without this seed, Vite's
// pre-bundler never sees those bare specifiers and Node module resolution
// walks up from inside .venv/site-packages — never reaching
// host/client_app/node_modules.
const manifestPath = path.resolve(__dirname, 'modules.manifest.json');
const moduleFsAllow: string[] = [];
const moduleOptimizeEntries: string[] = [];
const modulePkgJsonPaths: string[] = [];
if (fs.existsSync(manifestPath)) {
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8')) as Record<string, string>;
  for (const pagesDir of Object.values(manifest)) {
    moduleFsAllow.push(path.dirname(pagesDir));
    moduleOptimizeEntries.push(path.join(pagesDir, '**/*.tsx'));
    const modulePkgJson = path.join(path.dirname(pagesDir), 'package.json');
    if (fs.existsSync(modulePkgJson)) modulePkgJsonPaths.push(modulePkgJson);
  }
}

// CJS-only deps like `clsx`, `tailwind-merge`, `class-variance-authority`
// expose named exports only after esbuild's CJS→ESM transform. Vite's
// optimizer would normally pre-bundle them on first import, but the
// scanner sometimes misses bare imports inside wheel-installed pages
// because their importer paths sit outside the project root. Walking
// host/client_app/package.json + every dep's package.json one level
// deep and force-including the result keeps the named-import contract
// for everything pulled in transitively by `@simple-module-py/ui` etc.
type Pkg = {
  main?: string;
  module?: string;
  exports?: unknown;
  dependencies?: Record<string, string>;
};

const pkgCache = new Map<string, Pkg | null>();

function readPackageJSON(pkgJsonPath: string): Pkg | null {
  let pkg = pkgCache.get(pkgJsonPath);
  if (pkg !== undefined) return pkg;
  try {
    pkg = JSON.parse(fs.readFileSync(pkgJsonPath, 'utf-8')) as Pkg;
  } catch {
    pkg = null;
  }
  pkgCache.set(pkgJsonPath, pkg);
  return pkg;
}

function findPackageJSON(name: string): string | null {
  // npm hoists into `fsRoot/node_modules`; that's the only location worth
  // checking in workspace + flat layouts alike.
  const candidate = path.join(fsRoot, 'node_modules', name, 'package.json');
  return fs.existsSync(candidate) ? candidate : null;
}

function hasTopLevelEntry(pkg: Pkg): boolean {
  if (pkg.main || pkg.module) return true;
  const exp = pkg.exports;
  if (typeof exp === 'string') return true;
  if (exp && typeof exp === 'object') return '.' in exp;
  return false;
}

function collectOptimizeIncludes(): string[] {
  const includes = new Set<string>([
    ...REACT_CORE_DEPS,
    'react-dom/client',
    'use-sync-external-store',
    'use-sync-external-store/shim',
    'use-sync-external-store/shim/with-selector',
  ]);
  const visited = new Set<string>();
  const queue: string[] = [path.join(__dirname, 'package.json'), ...modulePkgJsonPaths];
  while (queue.length > 0) {
    const pkgJsonPath = queue.shift();
    if (!pkgJsonPath || visited.has(pkgJsonPath)) continue;
    visited.add(pkgJsonPath);
    const pkg = readPackageJSON(pkgJsonPath);
    if (!pkg) continue;
    for (const name of Object.keys(pkg.dependencies ?? {})) {
      if (name.startsWith('@types/')) continue;
      const nested = findPackageJSON(name);
      if (!nested) continue;
      const nestedPkg = readPackageJSON(nested);
      if (!nestedPkg) continue;
      // Skip packages that ship only sub-paths (`@babel/runtime`); vite
      // refuses to pre-bundle them and bare imports against them resolve
      // naturally through Node's normal module-walk anyway.
      if (hasTopLevelEntry(nestedPkg)) {
        includes.add(name);
      }
      queue.push(nested);
    }
  }
  return [...includes];
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  root: __dirname,
  resolve: {
    dedupe: [...REACT_CORE_DEPS, '@simple-module-py/ui', '@simple-module-py/i18n'],
  },
  optimizeDeps: {
    entries: ['main.tsx', 'pages/**/*.tsx', ...moduleOptimizeEntries],
    include: collectOptimizeIncludes(),
  },
  build: {
    outDir: '../static/dist',
    manifest: true,
    rollupOptions: {
      input: path.resolve(__dirname, 'main.tsx'),
    },
  },
  server: {
    port: 5050,
    strictPort: true,
    origin: 'http://localhost:5050',
    fs: {
      allow: [fsRoot, ...moduleFsAllow],
    },
  },
});
