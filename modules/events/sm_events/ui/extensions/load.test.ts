import { dirname, resolve } from 'node:path';
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
