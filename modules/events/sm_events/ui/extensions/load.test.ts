import { existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  extensionFailures,
  GLOB_PATTERN,
  loadEventExtensions,
  pluginGlobRoot,
  resetLoader,
} from './load';
import { clearExtensions, eventType, registerEventType } from './registry';

beforeEach(() => {
  clearExtensions();
  resetLoader();
});
afterEach(() => vi.restoreAllMocks());

describe('loadEventExtensions', () => {
  it('a throwing plugin does not stop the others, and is logged once by path', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    await loadEventExtensions({
      '../../../../acme/acme_pkg/events-extensions.ts': async () => {
        throw new Error('boom at top level');
      },
      '../../../../ok/ok_pkg/events-extensions.ts': async () => {
        registerEventType({ id: 'ok:talk' });
      },
      '../../../../dup/dup_pkg/events-extensions.ts': async () => {
        registerEventType({ id: 'ok:talk' }); // a registration that throws
      },
    });
    expect(eventType('ok:talk')).toBeDefined();
    const logged = error.mock.calls.map((c) => String(c[0]));
    expect(logged.filter((l) => l.includes('acme_pkg'))).toHaveLength(1);
    expect(logged.filter((l) => l.includes('dup_pkg'))).toHaveLength(1);
    expect(logged.some((l) => l.includes('ok_pkg'))).toBe(false);
    expect(extensionFailures().map((f) => f.path)).toEqual([
      '../../../../acme/acme_pkg/events-extensions.ts',
      '../../../../dup/dup_pkg/events-extensions.ts',
    ]);
    expect(JSON.stringify(extensionFailures())).not.toContain('boom'); // names, never messages
  });

  it('runs once', async () => {
    const loader = vi.fn(async () => {});
    const loaders = { '../../../../a/b/events-extensions.ts': loader };
    await Promise.all([loadEventExtensions(loaders), loadEventExtensions(loaders)]);
    await loadEventExtensions(loaders);
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it('loads nothing and still resolves when there are no plugin files', async () => {
    await expect(loadEventExtensions({})).resolves.toBeUndefined();
    expect(extensionFailures()).toEqual([]);
  });
});

describe('the glob', () => {
  it('is lazy and only ever names the one file', () => {
    expect(GLOB_PATTERN).toBe('../../../../*/*/events-extensions.ts');
  });

  it('pattern resolves in workspace and site-packages layouts', () => {
    const here = dirname(fileURLToPath(import.meta.url));
    expect(here.endsWith('sm_events/ui/extensions')).toBe(true);
    const workspace = pluginGlobRoot('/r/modules/events/sm_events/ui/extensions');
    expect(workspace).toBe(resolve('/r/modules'));
    const wheel = pluginGlobRoot('/r/.venv/lib/python3.12/site-packages/sm_events/ui/extensions');
    expect(wheel.endsWith('python3.12')).toBe(true);
    // `*/*` below it: workspace modules/<dist>/<pkg>, wheel python3.12/site-packages/<pkg>
  });
});

describe('what the glob matches in each layout', () => {
  const made: string[] = [];
  afterEach(() => {
    for (const dir of made.splice(0)) rmSync(dir, { recursive: true, force: true });
  });

  /** Build `files` under a temp root, run the pattern from `loaderDir`, return what it matched
   *  relative to the root. */
  function matched(loaderDir: string, files: string[]): string[] {
    const root = mkdtempSync(join(tmpdir(), 'events-glob-'));
    made.push(root);
    for (const file of [...files, `${loaderDir}/load.ts`]) {
      mkdirSync(dirname(join(root, file)), { recursive: true });
      writeFileSync(join(root, file), '');
    }
    // `GLOB_PATTERN` is four levels up, then `<a>/<b>/events-extensions.ts`: Vite resolves it
    // against the importer, so enumerate exactly that from the loader's directory.
    const base = resolve(join(root, loaderDir), '../../../..');
    const out: string[] = [];
    for (const a of readdirSync(base)) {
      for (const b of existsSync(join(base, a)) ? readdirSync(join(base, a)) : []) {
        const file = join(base, a, b, 'events-extensions.ts');
        if (existsSync(file)) out.push(file.slice(root.length + 1));
      }
    }
    return out.sort();
  }

  it('workspace: modules/<dist>/<package>/events-extensions.ts', () => {
    expect(
      matched('modules/events/sm_events/ui/extensions', [
        'modules/records/sm_records/events-extensions.ts',
        'modules/events/sm_events/ui/events-extensions.ts',
        'node_modules/@x/y/events-extensions.ts',
      ]),
    ).toEqual(['modules/records/sm_records/events-extensions.ts']);
  });

  it('wheel: <python lib>/site-packages/<package>/events-extensions.ts', () => {
    expect(
      matched('lib/python3.12/site-packages/sm_events/ui/extensions', [
        'lib/python3.12/site-packages/sm_records/events-extensions.ts',
        'lib/python3.12/site-packages/sm_records/deep/events-extensions.ts',
      ]),
    ).toEqual(['lib/python3.12/site-packages/sm_records/events-extensions.ts']);
  });

  it('node_modules: only packages beside events in the @simple-module-py scope', () => {
    expect(
      matched('node_modules/@simple-module-py/events/sm_events/ui/extensions', [
        'node_modules/@simple-module-py/records/sm_records/events-extensions.ts',
        'node_modules/@x/y/events-extensions.ts',
        'node_modules/@x/y/z/events-extensions.ts',
        'node_modules/some-package/events-extensions.ts',
        'node_modules/some-package/lib/events-extensions.ts',
      ]),
    ).toEqual(['node_modules/@simple-module-py/records/sm_records/events-extensions.ts']);
  });
});
