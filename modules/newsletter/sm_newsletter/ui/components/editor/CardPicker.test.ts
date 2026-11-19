import { describe, expect, it, vi } from 'vitest';

import type { CardSnapshot, EventCardSnapshot } from '../../utils/types';
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

const eventSnapshot: EventCardSnapshot = {
  id: 'server-id',
  source_id: '3f2c6c1e-8f4e-4a45-9d0e-0a5b8f6f1c11',
  title: 'Open day',
  excerpt: '',
  image_url: '',
  url: '/events/open-day',
  ics_url: '/events/open-day.ics',
  locale: 'en',
  starts_at: '2026-07-01T08:00:00Z',
  ends_at: '2026-07-01T09:00:00Z',
  all_day: false,
  start_date: null,
  end_date: null,
  timezone: 'Europe/Vienna',
  attendance_mode: 'in_person',
  place: '',
  cancelled: false,
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

describe('applySnapshot for an event', () => {
  it('replaces an EventCard, keeping its id', () => {
    const puck = fakePuck({ e1: { type: 'EventCard', index: 1 } });
    expect(applySnapshot(puck, 'e1', 'event', eventSnapshot)).toBe(true);
    expect(puck.dispatch).toHaveBeenCalledWith({
      type: 'replace',
      destinationIndex: 1,
      destinationZone: 'root:default-zone',
      data: { type: 'EventCard', props: { ...eventSnapshot, id: 'e1' } },
    });
  });

  it('refuses an ArticleCard, and an event snapshot never lands on a page card', () => {
    const puck = fakePuck({
      a1: { type: 'ArticleCard', index: 0 },
      p1: { type: 'PageCard', index: 1 },
    });
    expect(applySnapshot(puck, 'a1', 'event', eventSnapshot)).toBe(false);
    expect(applySnapshot(puck, 'p1', 'event', eventSnapshot)).toBe(false);
    expect(puck.dispatch).not.toHaveBeenCalled();
  });
});
