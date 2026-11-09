import { describe, expect, it } from 'vitest';

import { daysLeft, formatWhen, toUtcIso } from './progress';
import type { Progress } from './types';

function snap(queued: number, sending: number, daily_rate: number): Progress {
  return {
    status: 'sending',
    recipients: 1000,
    queued,
    sending,
    sent: 0,
    failed: 0,
    bounced: 0,
    suppressed: 0,
    skipped: 0,
    cancelled: 0,
    paused_code: null,
    paused_detail: null,
    scheduled_at: null,
    started_at: null,
    finished_at: null,
    estimated_finish: null,
    daily_rate,
  };
}

describe('daysLeft', () => {
  it('rounds the remaining days up', () => {
    expect(daysLeft(snap(250, 0, 100))).toBe(3);
    expect(daysLeft(snap(199, 1, 100))).toBe(2);
    expect(daysLeft(snap(1, 0, 100))).toBe(1);
  });

  it('is null when nothing is left, or no rate is known', () => {
    expect(daysLeft(snap(0, 0, 100))).toBeNull();
    expect(daysLeft(snap(10, 0, 0))).toBeNull();
  });
});

describe('toUtcIso', () => {
  it('reads a datetime-local value as local time', () => {
    const local = '2026-12-01T09:30';
    expect(toUtcIso(local)).toBe(new Date(2026, 11, 1, 9, 30).toISOString());
  });

  it('is null for an empty or invalid value', () => {
    expect(toUtcIso('')).toBeNull();
    expect(toUtcIso('not a date')).toBeNull();
    expect(toUtcIso('2026-13-45T99:99')).toBeNull();
  });
});

describe('formatWhen', () => {
  it('formats with a medium date and a short time in the given locale', () => {
    const iso = '2026-12-01T09:30:00Z';
    const expected = new Intl.DateTimeFormat('de', {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(iso));
    expect(formatWhen(iso, 'de')).toBe(expected);
  });

  it('returns the input for an unreadable timestamp', () => {
    expect(formatWhen('garbage', 'en')).toBe('garbage');
  });
});
