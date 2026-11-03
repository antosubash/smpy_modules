import { beforeEach, describe, expect, it } from 'vitest';

import {
  type AnyBlock,
  declareBuiltInBlocks,
  registeredBlocks,
  registerPuckBlocks,
  registryVersion,
  resetBlockRegistry,
} from './blockRegistry';

const stub = { render: () => null } as unknown as AnyBlock;

describe('block registry', () => {
  beforeEach(() => {
    declareBuiltInBlocks(['Heading', 'Text']);
    resetBlockRegistry();
  });

  it('collects a registration', () => {
    registerPuckBlocks({ blocks: { Widget: stub } });
    expect(registeredBlocks().flatMap((r) => Object.keys(r.blocks))).toContain('Widget');
  });

  it('bumps the version on each registration', () => {
    const before = registryVersion();
    registerPuckBlocks({ blocks: { Widget: stub } });
    expect(registryVersion()).toBeGreaterThan(before);
  });

  it('refuses to shadow a block pagebuilder already ships', () => {
    // Block names are the `type` stored in page content, so a duplicate would
    // make two blocks each render the other's saved data.
    expect(() => registerPuckBlocks({ blocks: { Heading: stub } })).toThrow(/Heading/);
  });

  it('refuses to register the same name twice', () => {
    registerPuckBlocks({ blocks: { Widget: stub } });
    expect(() => registerPuckBlocks({ blocks: { Widget: stub } })).toThrow(/Widget/);
  });

  it('keeps the built-ins reserved across a reset', () => {
    resetBlockRegistry();
    expect(() => registerPuckBlocks({ blocks: { Text: stub } })).toThrow(/Text/);
  });

  it('carries the category through', () => {
    registerPuckBlocks({ blocks: { Widget: stub }, category: { key: 'feeds', title: 'Feeds' } });
    expect(registeredBlocks()[0].category).toEqual({ key: 'feeds', title: 'Feeds' });
  });

  it('defaults to page-only, not layout', () => {
    registerPuckBlocks({ blocks: { Widget: stub } });
    expect(registeredBlocks()[0].layout).toBeUndefined();
  });
});
