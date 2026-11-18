import { describe, expect, it } from 'vitest';
import type { Occurrence } from '../../utils/types-events';
import { localTimeText, timeText } from './format';

const base: Occurrence = {
  source: 'events',
  key: 'k',
  calendar_id: 'c',
  start: '2026-03-23T09:00:00Z',
  end: '2026-03-23T10:00:00Z',
  all_day: false,
  timezone: 'Europe/Vienna',
  start_date: null,
  end_date: null,
  title: 'Talk',
  lang: 'en',
  color: '#000000',
  url: null,
  status: 'confirmed',
  type: 'event',
  editable: true,
  event_id: 'e',
  original_start: null,
  event_status: 'published',
};
const allDay: Occurrence = {
  ...base,
  all_day: true,
  start_date: '2026-03-29',
  end_date: '2026-03-30',
};

describe('timeText', () => {
  it('is dates only for all-day, whatever the zone', () => {
    const vienna = timeText(allDay, 'Europe/Vienna', 'en');
    expect(timeText(allDay, 'Pacific/Kiritimati', 'en')).toBe(vienna);
    expect(vienna).toContain('29');
    expect(vienna).not.toMatch(/\d:\d\d/);
  });
  it('shows a multi-day all-day event as an inclusive range', () => {
    const text = timeText({ ...allDay, end_date: '2026-04-01' }, 'UTC', 'en');
    expect(text).toContain('Mar 29');
    expect(text).toContain('Mar 31');
  });
  it('is the time in the grid zone', () => {
    expect(timeText(base, 'America/New_York', 'en')).toContain('5:00');
  });
});

describe('localTimeText', () => {
  it('is null when the zones agree', () => {
    expect(localTimeText(base, 'Europe/Vienna', 'en')).toBeNull();
  });
  it('is null for an all-day event', () => {
    expect(localTimeText(allDay, 'America/New_York', 'en')).toBeNull();
  });
  it('names the event zone when the grid differs', () => {
    const text = localTimeText(base, 'America/New_York', 'de');
    expect(text).toContain('10:00');
    expect(text).toContain('Europe/Vienna');
  });
});

describe('the repeated hour', () => {
  // Daily 02:30-03:00 in Vienna on 2026-10-25: half an hour from 02:30 CEST to 02:00 CET.
  const fold: Occurrence = {
    ...base,
    start: '2026-10-25T00:30:00Z',
    end: '2026-10-25T01:00:00Z',
  };
  it('names each end\'s offset instead of reading "2:30 – 2:00 AM"', () => {
    const text = timeText(fold, 'Europe/Vienna', 'en');
    expect(text).toMatch(/2:30\s?AM GMT\+2/);
    expect(text).toMatch(/2:00\s?AM GMT\+1/);
  });
  it('leaves an ordinary range alone', () => {
    expect(timeText(base, 'Europe/Vienna', 'en')).not.toContain('GMT');
  });
  it('is the popover text without a second zone name', () => {
    expect(localTimeText(base, 'America/New_York', 'en', false)).not.toContain('Europe/Vienna');
  });
});
