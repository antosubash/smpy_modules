/**
 * Give the unit tests the same catalogue the host serves.
 *
 * Every module's console strings live in `modules/<name>/<package>/locales`,
 * and the host merges them into one flat `<namespace>.<key>` map before
 * handing it to `configureI18n`. Without the same step here, `useT()` in a
 * component under test resolves nothing and every assertion about a label
 * would be an assertion about a raw key — so a real missing key would be
 * indistinguishable from the harness not being wired.
 *
 * Loaded by `vitest.config.ts` as a setup file, for every module: a module
 * that ships no `locales/` contributes nothing and needs no change here.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { configureI18n } from '@simple-module-py/i18n';

const MODULES = join(import.meta.dirname, '..', 'modules');

function flatten(node: Record<string, unknown>, prefix: string, out: Record<string, string>): void {
  for (const [name, value] of Object.entries(node)) {
    const key = `${prefix}.${name}`;
    if (typeof value === 'string') out[key] = value;
    else if (value && typeof value === 'object') {
      flatten(value as Record<string, unknown>, key, out);
    }
  }
}

function directories(path: string): string[] {
  try {
    return readdirSync(path).filter((name) => statSync(join(path, name)).isDirectory());
  } catch {
    return [];
  }
}

const messages: Record<string, string> = {};

for (const namespace of directories(MODULES)) {
  // The namespace is the *module* directory (`modules/<name>`), the same name
  // every `locale_dirs()` registers its catalogue under — not the package
  // directory, which differs for the `sm_*` packages (`sm_billing` → `billing`).
  for (const pkg of directories(join(MODULES, namespace))) {
    const file = join(MODULES, namespace, pkg, 'locales', 'en.json');
    try {
      flatten(JSON.parse(readFileSync(file, 'utf-8')), namespace, messages);
    } catch {
      // No catalogue in this package, which is the ordinary case for the
      // directories that are not a module's Python package.
    }
  }
}

configureI18n({ locale: 'en', messages });
