// @vitest-environment happy-dom
import { expect, it } from 'vitest';
import { mount } from '../page-tests/test-dom';
import { EventChip } from './EventChip';
import type { EventChipProps } from './types';

const base = {
  source: 'events',
  key: 'k',
  calendar_id: 'c',
  start: '2026-03-23T09:00:00Z',
  end: '2026-03-23T09:30:00Z',
  all_day: false,
  timezone: 'Europe/Vienna',
  start_date: null,
  end_date: null,
  title: 'Standup',
  lang: 'en',
  color: '#2563eb',
  url: null,
  status: 'confirmed',
  type: 'event',
  editable: true,
  event_id: 'e',
  original_start: null,
  event_status: 'published',
} as const;

async function texts(props: Partial<EventChipProps> & Pick<EventChipProps, 'occurrence'>) {
  const view = await mount(
    <EventChip view="week" timeText="10:00 AM" Default={EventChip} {...props} />,
  );
  const order = [...view.host.querySelectorAll('[data-ev-title], .tabular-nums')].map((e) =>
    e.hasAttribute('data-ev-title') ? 'title' : 'time',
  );
  await view.unmount();
  return order;
}

it('puts the title before the time in a short week block', async () => {
  expect(await texts({ occurrence: { ...base } })).toEqual(['title', 'time']);
});

it('keeps the time first in a long block, a month cell and an all-day chip', async () => {
  const long = { ...base, end: '2026-03-23T10:00:00Z' };
  expect(await texts({ occurrence: long })).toEqual(['time', 'title']);
  expect(await texts({ occurrence: { ...base }, view: 'month' })).toEqual(['time', 'title']);
});

it('clips a very long title with an ellipsis at three lines, breaking inside the word', async () => {
  const long = { ...base, title: 'W'.repeat(400), end: '2026-03-23T11:00:00Z' };
  const view = await mount(
    <EventChip view="day" timeText="10:00 AM" Default={EventChip} occurrence={long} />,
  );
  const title = view.host.querySelector('[data-ev-title]') as HTMLElement;
  expect(title.className).toContain('line-clamp-3');
  expect(title.className).toContain('[overflow-wrap:anywhere]');
  await view.unmount();
});
