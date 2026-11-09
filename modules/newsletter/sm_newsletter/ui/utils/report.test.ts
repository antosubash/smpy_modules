import { afterEach, describe, expect, it } from 'vitest';

import { bucketLabel, formatRate, hasStarted, rate } from './report';

const realTz = process.env.TZ;
afterEach(() => {
  if (realTz === undefined) delete process.env.TZ;
  else process.env.TZ = realTz;
});

describe('rate', () => {
  it('is null when the whole is not positive', () => {
    expect(rate(1, 0)).toBeNull();
    expect(rate(0, -1)).toBeNull();
  });
  it('divides', () => {
    expect(rate(1, 4)).toBe(0.25);
  });
  it('never clamps (the server guarantees at most 1)', () => {
    expect(rate(3, 2)).toBe(1.5);
  });
});

describe('formatRate', () => {
  it('formats a percent with the locale', () => {
    expect(formatRate(0.25, 'de')).toContain('25');
    expect(formatRate(0.256, 'en')).toBe('25.6%');
  });
  it('passes null through', () => {
    expect(formatRate(null, 'en')).toBeNull();
  });
});

describe('bucketLabel', () => {
  it('shows the UTC hour whatever the local zone', () => {
    process.env.TZ = 'Pacific/Auckland';
    const label = bucketLabel('2026-11-05T23:00:00Z', 'hour', 'en');
    expect(label).toContain('23:00');
    expect(label).toContain('5');
    expect(label).toContain('Nov');
  });
  it.each(['de', 'fr'])('shows HH:00 without locale words in %s', (locale) => {
    process.env.TZ = 'Pacific/Auckland';
    const label = bucketLabel('2026-11-05T23:00:00Z', 'hour', locale);
    expect(label).toContain('23:00');
    expect(label).not.toContain('Uhr');
    expect(label).not.toMatch(/\sh\b/);
  });
  it('shows only the UTC date for a day bucket', () => {
    process.env.TZ = 'Pacific/Auckland';
    const label = bucketLabel('2026-11-05T23:00:00Z', 'day', 'en');
    expect(label).toContain('Nov');
    expect(label).toContain('5');
    expect(label).not.toContain(':');
  });
});

describe('hasStarted', () => {
  const at = '2026-11-05T10:00:00Z';
  it.each(['sending', 'paused', 'sent', 'cancelled'])(
    'is true for %s with started_at',
    (status) => {
      expect(hasStarted({ status, started_at: at })).toBe(true);
    },
  );
  it.each(['draft', 'scheduled'])('is false for %s', (status) => {
    expect(hasStarted({ status, started_at: at })).toBe(false);
    expect(hasStarted({ status, started_at: null })).toBe(false);
  });
  it.each(['sending', 'paused', 'sent', 'cancelled'])(
    'is false for %s without started_at',
    (status) => {
      expect(hasStarted({ status, started_at: null })).toBe(false);
    },
  );
});
