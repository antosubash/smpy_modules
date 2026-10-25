import { describe, expect, it } from 'vitest';
import { describeError } from './api';
import {
  formatBytes,
  formatQuantity,
  kindLabel,
  parseAdjustQuantity,
  percentOf,
  usageTone,
} from './usage';

describe('usage formatting', () => {
  it('formats bytes in SI units in the given locale', () => {
    expect(formatBytes(512, 'en')).toBe('512 byte');
    expect(formatBytes(1_500_000, 'en')).toBe('1.5 MB');
    expect(formatBytes(1_500_000, 'de')).toBe('1,5 MB');
  });

  it('formats a quantity in its unit', () => {
    expect(formatQuantity(5000, 'tokens', 'en')).toBe('5,000 tokens');
    expect(formatQuantity(350, 'ms', 'en')).toBe('350 ms');
    expect(formatQuantity(1200, 'count', 'de')).toBe('1.200');
    expect(formatQuantity(7, 'furlongs', 'en')).toBe('7');
  });

  it('computes percent and tone the way the server does', () => {
    expect(percentOf(5, null)).toBeNull();
    expect(percentOf(1, 3)).toBe(33.3);
    expect(percentOf(0, 0)).toBe(0);
    expect(percentOf(1, 0)).toBe(100);
    expect([usageTone(null), usageTone(89.9), usageTone(90), usageTone(100)]).toEqual([
      'normal',
      'normal',
      'warning',
      'over',
    ]);
  });

  it('parses a signed, non-zero whole quantity', () => {
    expect(parseAdjustQuantity('-3')).toBe(-3);
    expect(parseAdjustQuantity(' +12 ')).toBe(12);
    for (const bad of ['', '0', '-0', '1.5', '1e3', 'x', '99999999999999999999']) {
      expect(parseAdjustQuantity(bad)).toBeNull();
    }
  });

  it('labels ledger kinds, passing unknown ones through', () => {
    expect(kindLabel('adjust')).toBe('Adjusted');
    expect(kindLabel('mystery')).toBe('mystery');
  });
});

describe('quota_exceeded', () => {
  it('names the meter, the numbers and the reset date', () => {
    const message = describeError('quota_exceeded', {
      meter: 'ai.requests',
      used: 10,
      limit: 10,
      requested: 1,
      resets_at: '2026-11-01T00:00:00+00:00',
    });
    expect(message).toBe('ai.requests limit reached (10/10); resets Nov 1, 2026.');
  });

  it('leaves the date out for a gauge, which never resets', () => {
    const message = describeError('quota_exceeded', {
      meter: 'jobs.concurrent',
      used: 2,
      limit: 2,
      requested: 1,
      resets_at: null,
    });
    expect(message).toBe('jobs.concurrent limit reached (2/2).');
  });
});
