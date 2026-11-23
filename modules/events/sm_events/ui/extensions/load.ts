/** Finding the plugins: a lazy, guarded glob of every package's `events-extensions.ts`.
 *
 *  `../../../../` from `sm_events/ui/extensions/` is `modules/` in the workspace and the Python
 *  lib directory (`python3.12`) in a wheel install, so `*` `/` `*` is `<dist>/<package>` in one and
 *  `site-packages/<package>` in the other (pagebuilder's block glob, one level deeper). It is
 *  *lazy*: an eager glob would let one plugin's top-level throw take down the bundle and would
 *  import it before this module exists. Each file is loaded on its own, so one that fails to load,
 *  or throws while registering, is logged once by path and skipped; the rest still register. */
import { useSyncExternalStore } from 'react';
import { registerBuiltins } from './builtins';

export const GLOB_PATTERN = '../../../../*/*/events-extensions.ts';

/** The directory the glob starts from, for a module directory (`dir` = `sm_events/ui/extensions`). */
export function pluginGlobRoot(dir: string): string {
  const parts = dir.split('/').filter((part) => part !== '');
  return `/${parts.slice(0, -4).join('/')}`;
}

type Loaders = Record<string, () => Promise<unknown>>;
export type ExtensionFailure = { path: string };

const found = import.meta.glob('../../../../*/*/events-extensions.ts') as Loaders;

let started: Promise<void> | null = null;
let ready = false;
let failures: ExtensionFailure[] = [];
const listeners = new Set<() => void>();

const announce = () => {
  for (const listener of listeners) listener();
};

/** The plugin files that failed (names only, never a message: it may name data). */
export const extensionFailures = (): readonly ExtensionFailure[] => failures;

/** Load every plugin once; concurrent and later calls share the one run. */
export function loadEventExtensions(loaders: Loaders = found): Promise<void> {
  started ??= (async () => {
    registerBuiltins();
    const entries = Object.entries(loaders);
    const settled = await Promise.allSettled(entries.map(([, load]) => load()));
    settled.forEach((result, index) => {
      if (result.status === 'rejected') {
        const path = entries[index]?.[0] ?? '?';
        failures = [...failures, { path }];
        console.error(`events: the extension ${path} could not be loaded`);
      }
    });
    ready = true;
    announce();
  })();
  return started;
}

/** Tests only. */
export function resetLoader(): void {
  started = null;
  ready = false;
  failures = [];
  announce();
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => void listeners.delete(listener);
};

/** Whether the plugins have registered (until then, defaults render). Starts the load. */
export function useEventExtensions(): boolean {
  void loadEventExtensions();
  return useSyncExternalStore(
    subscribe,
    () => ready,
    () => false,
  );
}
