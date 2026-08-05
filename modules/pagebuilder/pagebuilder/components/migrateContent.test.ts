import type { Data } from '@puckeditor/core';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { migrateContent } from './migrateContent';
import { getPuckConfig } from './puckConfig';

/** A payload in the shape the current build writes. */
const modern = {
  content: [{ type: 'Heading', props: { id: 'h1', text: 'Modern', level: 'h2', align: 'left' } }],
  root: { props: { title: 'Page', width: 'contained' } },
} as unknown as Data;

describe('migrateContent', () => {
  afterEach(() => vi.restoreAllMocks());

  it('returns modern data by identity, without walking it', () => {
    // Identity rather than deep equality: the point of the version check is
    // that the common path allocates nothing. A structural copy would pass
    // toEqual and still have paid for both tree walks.
    const log = vi.spyOn(console, 'log').mockImplementation(() => {});
    expect(migrateContent(modern, getPuckConfig())).toBe(modern);
    expect(log).not.toHaveBeenCalledWith(expect.stringContaining('Migrating DropZones'));
  });

  it('survives a Columns zone, which cannot migrate while Columns uses DropZone', () => {
    // Documents a real limitation, not a hypothetical one. `Columns` is the
    // only nesting block we ship and it renders `<DropZone zone="col-N">`;
    // migrate() can only convert a zone into a *slot field* of the same name,
    // and no component in our config declares one. So every stored page with a
    // populated zones map takes the catch path below — which is precisely why
    // this module exists, and why the Columns→slots port is a prerequisite for
    // zone migration ever succeeding rather than optional cleanup.
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const legacy = {
      content: [{ type: 'Columns', props: { id: 'C1', columns: [{}, {}] } }],
      root: { props: {} },
      zones: {
        'C1:col-0': [{ type: 'Heading', props: { id: 'h1', text: 'Nested', level: 'h2' } }],
      },
    } as unknown as Data;

    const result = migrateContent(legacy, getPuckConfig());

    expect(result).toBe(legacy);
    expect(error).toHaveBeenCalled();
    // The zones map is left intact, so the nested heading is still reachable
    // by the renderer's legacy DropZone path.
    expect(
      (result as unknown as { zones: Record<string, unknown> }).zones['C1:col-0'],
    ).toBeTruthy();
  });

  it('leaves an empty zones map alone', () => {
    // Puck writes `zones: {}` on pages that once held a DropZone and no longer
    // do. Treating that as legacy would migrate every such page on every
    // public request forever.
    const emptyZones = { ...modern, zones: {} } as unknown as Data;
    expect(migrateContent(emptyZones, getPuckConfig())).toBe(emptyZones);
  });

  it('migrates root props not yet nested under root.props', () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const legacyRoot = {
      content: [],
      root: { title: 'Old shape' },
    } as unknown as Data;
    expect(migrateContent(legacyRoot, getPuckConfig())).not.toBe(legacyRoot);
  });

  it('returns the original data when migration throws', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'log').mockImplementation(() => {});
    // A zone whose owning component isn't in the tree: migrate() has no slot
    // field to resolve it against.
    const unmigratable = {
      content: [{ type: 'Heading', props: { id: 'h1', text: 'Survives', level: 'h2' } }],
      root: { props: {} },
      zones: { 'ghost-1:nowhere': [{ type: 'Heading', props: { id: 'h2', text: 'Orphan' } }] },
    } as unknown as Data;

    const result = migrateContent(unmigratable, getPuckConfig());

    expect(error).toHaveBeenCalled();
    // The guarantee: one bad zone costs you that zone, not the document.
    expect(result.content?.[0]?.props?.text).toBe('Survives');
  });
});
