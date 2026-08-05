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

  it('folds Columns zones into the per-column array slots', () => {
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const legacy = {
      content: [{ type: 'Columns', props: { id: 'C1', gap: 'md', columns: [{}, {}] } }],
      root: { props: {} },
      zones: {
        'C1:col-0': [{ type: 'Heading', props: { id: 'h1', text: 'Left', level: 'h2' } }],
        'C1:col-1': [{ type: 'Text', props: { id: 't1', text: 'Right' } }],
      },
    } as unknown as Data;

    const result = migrateContent(legacy, getPuckConfig());

    expect((result as unknown as { zones?: unknown }).zones).toBeUndefined();
    const columns = result.content?.[0]?.props?.columns as { content: { props: unknown }[] }[];
    expect(columns[0].content[0].props).toMatchObject({ text: 'Left' });
    expect(columns[1].content[0].props).toMatchObject({ text: 'Right' });
  });

  it('recovers a zone whose column was deleted before the migration', () => {
    // A page saved after a column was removed still carries that column's
    // zone. Sizing the result to the zone indices as well as the stored array
    // means the orphaned block resurfaces in a real column instead of being
    // dropped on the floor — silently losing author content during a migration
    // is the one failure mode here that can't be undone.
    vi.spyOn(console, 'log').mockImplementation(() => {});
    const legacy = {
      content: [{ type: 'Columns', props: { id: 'C1', gap: 'md', columns: [{ width: 1 }] } }],
      root: { props: {} },
      zones: {
        'C1:col-1': [{ type: 'Heading', props: { id: 'h9', text: 'Orphan', level: 'h2' } }],
      },
    } as unknown as Data;

    const result = migrateContent(legacy, getPuckConfig());

    const columns = result.content?.[0]?.props?.columns as { content: { props: unknown }[] }[];
    expect(columns).toHaveLength(2);
    expect(columns[1].content[0].props).toMatchObject({ text: 'Orphan' });
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
