import { describe, expect, it } from 'vitest';
import type { CalendarInfo } from '../types';
import {
  addDays,
  dateIn,
  gridTimeZone,
  isDate,
  isRepeatedSecond,
  shiftLocal,
  toInstant,
  toLocal,
} from './zones';

const cal = (id: string, tz: string): CalendarInfo => ({
  id,
  name: id,
  color: '#000000',
  visibility: 'internal',
  default_timezone: tz,
  can_write_events: true,
});

describe('toLocal', () => {
  it('follows the EU change', () => {
    expect(toLocal('2026-03-30T09:00:00Z', 'Europe/Vienna')).toBe('2026-03-30T11:00');
    expect(toLocal('2026-03-23T09:00:00Z', 'Europe/Vienna')).toBe('2026-03-23T10:00');
  });
  it('keeps non-zero seconds', () => {
    expect(toLocal('2026-01-12T09:00:30Z', 'Europe/Vienna')).toBe('2026-01-12T10:00:30');
  });
});

describe('toInstant', () => {
  it('round-trips outside gaps and folds', () => {
    const zones = [
      'Europe/Vienna',
      'America/New_York',
      'Australia/Lord_Howe',
      'Pacific/Apia',
      'Asia/Kolkata',
    ];
    let seed = 20260318;
    const next = () => {
      seed = (seed * 1664525 + 1013904223) % 4294967296;
      return seed / 4294967296;
    };
    const from = Date.UTC(2025, 0, 1);
    const span = Date.UTC(2028, 0, 1) - from;
    for (let n = 0; n < 300; n += 1) {
      const minutes = Math.floor((next() * span) / 60000);
      const instant = new Date(from + minutes * 60000).toISOString().replace('.000Z', 'Z');
      const zone = zones[n % zones.length] as string;
      if (isRepeatedSecond(instant, zone)) continue;
      expect(toInstant(toLocal(instant, zone), zone)).toBe(instant);
    }
  });
  it('matches the server on a gap: shifted forward', () => {
    expect(toInstant('2026-03-29T02:30', 'Europe/Vienna')).toBe('2026-03-29T01:30:00Z');
  });
  it('takes the earlier instant on a fold, as the server does', () => {
    expect(toInstant('2026-10-25T02:30', 'Europe/Vienna')).toBe('2026-10-25T00:30:00Z');
  });
});

describe('isRepeatedSecond', () => {
  it('flags the second 02:30 on the Vienna fold only', () => {
    expect(isRepeatedSecond('2026-10-25T01:30:00Z', 'Europe/Vienna')).toBe(true);
    expect(isRepeatedSecond('2026-10-25T00:30:00Z', 'Europe/Vienna')).toBe(false);
    expect(isRepeatedSecond('2026-07-01T08:00:00Z', 'Europe/Vienna')).toBe(false);
  });
});

describe('shiftLocal', () => {
  it('adds a wall-clock difference', () => {
    expect(shiftLocal('2026-03-02T10:00', '2026-03-23T10:00', '2026-03-30T11:00')).toBe(
      '2026-03-09T11:00',
    );
  });
});

describe('gridTimeZone', () => {
  const a = cal('a', 'Europe/Vienna');
  const b = cal('b', 'Asia/Kolkata');
  it('is the one shown calendar zone', () => {
    expect(gridTimeZone('calendar', [a], 'UTC', 'America/New_York')).toBe('Europe/Vienna');
  });
  it('is the tenant default for several or none', () => {
    expect(gridTimeZone('calendar', [a, b], 'UTC')).toBe('UTC');
    expect(gridTimeZone('calendar', [], 'UTC')).toBe('UTC');
  });
  it('is the injected browser zone in my time', () => {
    expect(gridTimeZone('mine', [a], 'UTC', 'America/New_York')).toBe('America/New_York');
  });
});

describe('dates', () => {
  it('addDays crosses month ends', () => {
    expect(addDays('2026-01-31', 1)).toBe('2026-02-01');
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28');
  });
  it('dateIn reads the date in the zone', () => {
    expect(dateIn('2026-03-29T23:30:00Z', 'Europe/Vienna')).toBe('2026-03-30');
    expect(dateIn('2026-03-29T23:30:00Z', 'America/New_York')).toBe('2026-03-29');
  });
  it('isDate rejects malformed and impossible dates', () => {
    expect(isDate('2026-03-30')).toBe(true);
    expect(isDate('2026-02-30')).toBe(false);
    expect(isDate('2026-3-30')).toBe(false);
    expect(isDate('soon')).toBe(false);
  });
});
