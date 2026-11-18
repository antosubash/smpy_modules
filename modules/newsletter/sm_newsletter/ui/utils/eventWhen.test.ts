import { describe, expect, it } from 'vitest';

import { formatEventWhen } from './eventWhen';

const base = {
  starts_at: '2026-07-01T08:00:00Z',
  ends_at: '2026-07-01T09:30:00Z',
  all_day: false,
  start_date: null,
  end_date: null,
  timezone: 'Europe/Vienna',
};

// Intl spells the separators its own way; the editor's line is a preview, so compare loosely.
const flat = (s: string) => s.replace(/[\u202f\u00a0]/g, ' ').replace(/\s+/g, ' ');

describe('formatEventWhen', () => {
  it('names the time in the event zone, in the editor language', () => {
    const got = flat(formatEventWhen(base, 'de'));
    expect(got).toContain('1. Juli 2026');
    expect(got).toContain('10:00');
    expect(got).toMatch(/MESZ|GMT\+2|CEST/);
  });

  it('is the event zone, not the reader zone', () => {
    const got = flat(formatEventWhen({ ...base, timezone: 'America/New_York' }, 'en'));
    expect(got).toContain('4:00');
  });

  it('shows an all-day event as dates, the last one inclusive', () => {
    const got = flat(
      formatEventWhen(
        {
          ...base,
          all_day: true,
          start_date: '2026-08-01',
          end_date: '2026-08-04',
        },
        'de',
      ),
    );
    expect(got).toContain('1. August 2026');
    expect(got).toContain('3. August 2026');
    expect(got).not.toContain('4. August');
  });

  it('shows one all-day date once', () => {
    const got = flat(
      formatEventWhen(
        { ...base, all_day: true, start_date: '2026-03-29', end_date: '2026-03-30' },
        'en',
      ),
    );
    expect(got.match(/March/g)).toHaveLength(1);
  });

  it('shows a multi-day timed event with both ends', () => {
    const got = flat(formatEventWhen({ ...base, ends_at: '2026-07-02T07:00:00Z' }, 'en'));
    expect(got).toContain('July 1');
    expect(got).toContain('July 2');
  });
});
