// @vitest-environment happy-dom
import { act, type ComponentType, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';

import type { EventCardSnapshot } from '../../../utils/types';
import { eventCardBlock } from './eventCard';

vi.mock('../CardPicker', () => ({ cardField: () => ({ type: 'custom', render: () => null }) }));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const snapshot: EventCardSnapshot = {
  id: 'e1',
  source_id: '3f2c6c1e-8f4e-4a45-9d0e-0a5b8f6f1c11',
  title: 'Open day',
  excerpt: 'Come by',
  image_url: '',
  url: '/events/open-day',
  ics_url: '/events/open-day.ics',
  locale: 'en',
  starts_at: '2026-07-01T08:00:00Z',
  ends_at: '2026-07-01T09:30:00Z',
  all_day: false,
  start_date: null,
  end_date: null,
  timezone: 'Europe/Vienna',
  attendance_mode: 'in_person',
  place: 'Hall 1, Main St 2',
  cancelled: false,
  snapshot_at: '2026-11-01T00:00:00Z',
};

async function show(props: Partial<EventCardSnapshot>, available = true): Promise<string> {
  const config = eventCardBlock(available);
  const host = document.body.appendChild(document.createElement('div'));
  const root = createRoot(host);
  const Render = config.render as unknown as ComponentType<Record<string, unknown>>;
  await act(async () =>
    root.render(createElement(Render, { ...config.defaultProps, ...props, id: 'e1' })),
  );
  return host.textContent ?? '';
}

describe('eventCardBlock', () => {
  it('an empty card shows the empty note', async () => {
    const text = await show({});
    expect(text).toContain('Choose an item');
  });

  it('a snapshot shows its title, the when-line with the zone, and the place', async () => {
    const text = (await show(snapshot)).replace(/[\u202f\u00a0]/g, ' ');
    expect(text).toContain('Open day');
    expect(text).toContain('Hall 1, Main St 2');
    expect(text).toMatch(/10:00/);
    expect(text).toMatch(/CEST|GMT\+2/);
    expect(text).not.toContain('Cancelled');
  });

  it('marks a cancelled event', async () => {
    expect(await show({ ...snapshot, cancelled: true })).toContain('Cancelled');
  });

  it('never prints the event id', async () => {
    expect(await show(snapshot)).not.toContain(snapshot.source_id);
  });

  it('is always defined, with one field, whether or not the integration is there', () => {
    for (const available of [true, false]) {
      const config = eventCardBlock(available);
      expect(Object.keys(config.fields ?? {})).toEqual(['source_id']);
    }
  });
});
