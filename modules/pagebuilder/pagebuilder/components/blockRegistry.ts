/**
 * Lets another module contribute Puck blocks without pagebuilder importing it.
 *
 * The framework's registries — menu, permissions, public routes, design packs —
 * are all backend. This is the frontend equivalent, and the reason it exists is
 * dependency direction: the news module knows about pagebuilder, so pagebuilder
 * must not know about news.
 *
 * Registration is a side effect of importing a module's `puck-blocks.ts`. The
 * host imports them all eagerly at app start (see `host/client_app/blocks.ts`),
 * which is what guarantees the registry is populated before the first render.
 */

import type { ComponentConfig } from '@measured/puck';

// Puck's ComponentConfig is invariant in its props, so a registry that holds
// configs for unrelated prop shapes cannot be typed precisely. The runtime
// shape is what matters here; each module keeps its own widget types honest.
// biome-ignore lint/suspicious/noExplicitAny: a heterogeneous registry has no single prop type
export type AnyBlock = ComponentConfig<any>;

export interface BlockRegistration {
  /** Block name → config. The name is the `type` stored in page content. */
  blocks: Record<string, AnyBlock>;
  /** Palette group. Blocks with no category land in Puck's "Other". */
  category?: { key: string; title: string };
  /** Also offer these in the site-layout palette. Default false. */
  layout?: boolean;
}

let registrations: BlockRegistration[] = [];
let takenNames = new Set<string>();
let builtIns: readonly string[] = [];
let version = 0;

/**
 * Declare the names pagebuilder itself ships, so a module cannot shadow one.
 *
 * Called once by puckConfig at import time rather than hardcoded here, which
 * would be a second list to keep in sync.
 */
export function declareBuiltInBlocks(names: readonly string[]): void {
  builtIns = names;
  for (const name of names) takenNames.add(name);
}

export function registerPuckBlocks(registration: BlockRegistration): void {
  for (const name of Object.keys(registration.blocks)) {
    if (takenNames.has(name)) {
      throw new Error(
        `Puck block "${name}" is already registered. Block names are the \`type\` ` +
          'stored in page content, so two blocks sharing one would each render ' +
          "the other's saved data.",
      );
    }
    takenNames.add(name);
  }
  registrations = [...registrations, registration];
  version += 1;
}

export function registeredBlocks(): readonly BlockRegistration[] {
  return registrations;
}

/**
 * Bumped on every registration. The config builders memoise on this rather
 * than caching unconditionally, so a registration that lands after the first
 * read is not silently dropped.
 */
export function registryVersion(): number {
  return version;
}

/** Test-only: drop every registration, keeping the declared built-ins. */
export function resetBlockRegistry(): void {
  registrations = [];
  takenNames = new Set(builtIns);
  version += 1;
}
