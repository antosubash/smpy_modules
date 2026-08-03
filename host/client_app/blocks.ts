/**
 * Run every module's Puck block registration, eagerly, before anything renders.
 *
 * Module *pages* are imported lazily by Inertia's resolver, which is far too
 * late — a pagebuilder page reads the Puck config while rendering. Importing
 * the registrations from the app entry is what guarantees the registry is
 * populated first.
 *
 * Two globs because workspace modules and wheel-installed modules live in
 * different trees, the same split modules.generated.ts uses for pages. This
 * file is hand-written for the same reason styles.css's module imports are:
 * gen-pages emits page globs and @source entries, not block imports.
 *
 * A glob that matches nothing is not an error, so this is harmless in a host
 * whose modules contribute no blocks.
 */
import.meta.glob('../../modules/*/*/puck-blocks.ts', { eager: true });
import.meta.glob('../../.venv/lib/python3.12/site-packages/*/puck-blocks.ts', { eager: true });
