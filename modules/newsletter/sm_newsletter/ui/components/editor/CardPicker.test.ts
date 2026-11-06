import { describe, expect, it, vi } from 'vitest';

import type { CardSnapshot } from '../../utils/types';
import { applySnapshot } from './CardPicker';

const snapshot: CardSnapshot = {
  id: 'server-id',
  source_id: 9,
  title: 'Spring sale',
  excerpt: '',
  image_url: '',
  url: '/p/spring',
  locale: 'en',
  snapshot_at: '2026-11-01T00:00:00Z',
};

function fakePuck(items: Record<string, { type: string; index: number }>) {
  return {
    getItemById: (id: string) =>
      items[id] ? ({ type: items[id].type, props: { id } } as never) : undefined,
    getSelectorForId: (id: string) =>
      items[id] ? { index: items[id].index, zone: 'root:default-zone' } : undefined,
    dispatch: vi.fn(),
  };
}

describe('applySnapshot', () => {
  it('replaces the card it was asked for, by id, keeping that id', () => {
    const puck = fakePuck({
      c1: { type: 'PageCard', index: 2 },
      h1: { type: 'Heading', index: 0 },
    });
    expect(applySnapshot(puck, 'c1', 'page', snapshot)).toBe(true);
    expect(puck.dispatch).toHaveBeenCalledWith({
      type: 'replace',
      destinationIndex: 2,
      destinationZone: 'root:default-zone',
      data: { type: 'PageCard', props: { ...snapshot, id: 'c1' } },
    });
  });

  it('writes nothing when the block is gone', () => {
    const puck = fakePuck({ h1: { type: 'Heading', index: 0 } });
    expect(applySnapshot(puck, 'c1', 'page', snapshot)).toBe(false);
    expect(puck.dispatch).not.toHaveBeenCalled();
  });

  it('never overwrites a block that is not a card of that kind', () => {
    const puck = fakePuck({
      h1: { type: 'Heading', index: 0 },
      a1: { type: 'ArticleCard', index: 1 },
    });
    expect(applySnapshot(puck, 'h1', 'page', snapshot)).toBe(false);
    expect(applySnapshot(puck, 'a1', 'page', snapshot)).toBe(false);
    expect(puck.dispatch).not.toHaveBeenCalled();
  });
});
