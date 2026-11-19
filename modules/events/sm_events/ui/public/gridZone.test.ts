import { describe, expect, it } from 'vitest';
import type { CalendarInfo } from '../calendar/types';
import { publicGridZone } from './gridZone';

const cal = (zone: string, id = zone): CalendarInfo => ({
  id,
  name: id,
  color: '#000',
  visibility: 'public',
  default_timezone: zone,
  can_write_events: false,
});

describe('publicGridZone', () => {
  it('one calendar: its own zone, offered as "calendar time"', () => {
    expect(publicGridZone([cal('Europe/Vienna')], 'America/New_York')).toEqual({
      defaultTimezone: 'Europe/Vienna',
      tzMode: 'calendar',
      calendarTime: true,
    });
  });

  it('several calendars in one zone: that zone, never the host default', () => {
    const got = publicGridZone([cal('Europe/Vienna', 'a'), cal('Europe/Vienna', 'b')], 'UTC');
    expect(got).toEqual({
      defaultTimezone: 'Europe/Vienna',
      tzMode: 'calendar',
      calendarTime: true,
    });
  });

  it('calendars in different zones: the visitor\'s own zone, and no "calendar time"', () => {
    const got = publicGridZone([cal('Europe/Vienna', 'a'), cal('Asia/Tokyo', 'b')], 'UTC');
    expect(got).toEqual({ defaultTimezone: 'UTC', tzMode: 'mine', calendarTime: false });
  });

  it("no calendars: nothing to be wrong about, the visitor's zone", () => {
    expect(publicGridZone([], 'UTC').tzMode).toBe('mine');
  });
});
