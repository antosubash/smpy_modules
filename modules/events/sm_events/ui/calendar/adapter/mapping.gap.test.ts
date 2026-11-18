import { describe, expect, it } from 'vitest';
import { skipsWallTime } from './mapping';

describe('skipsWallTime', () => {
  const zero = { years: 0, months: 0, days: 0, milliseconds: 0 };
  const edited = (startStr: string, endStr: string) => ({
    start: null,
    end: null,
    allDay: false,
    startStr,
    endStr,
  });
  const old = edited('2026-03-28T10:00:00+01:00', '2026-03-28T11:00:00+01:00');
  const VIENNA = 'Europe/Vienna';

  it('flags a move whose wall time the zone skips (K5)', () => {
    // 28 March 10:00 + 16 h 30 min = 29 March 02:30, which Vienna does not have.
    const delta = { ...zero, days: 0, milliseconds: 16.5 * 3_600_000 };
    expect(skipsWallTime('move', old, { delta }, VIENNA)).toBe(true);
  });
  it('lets a move onto a real wall time through, across the clock change', () => {
    const delta = { ...zero, days: 1, milliseconds: 5 * 3_600_000 - 7 * 3_600_000 };
    expect(skipsWallTime('move', old, { delta }, VIENNA)).toBe(false);
  });
  it('judges a resize by the pulled edge only', () => {
    const early = edited('2026-03-29T01:00:00+01:00', '2026-03-29T01:30:00+01:00');
    const endDelta = { ...zero, milliseconds: 1.5 * 3_600_000 }; // end 03:00 wall: fine
    expect(skipsWallTime('resize', early, { startDelta: zero, endDelta }, VIENNA)).toBe(false);
    const skipped = { ...zero, milliseconds: 1 * 3_600_000 }; // end 02:30 wall: skipped
    expect(skipsWallTime('resize', early, { startDelta: zero, endDelta: skipped }, VIENNA)).toBe(
      true,
    );
  });
  it('never flags an all-day drop', () => {
    const day = { ...edited('2026-03-28', '2026-03-29'), allDay: true };
    expect(skipsWallTime('move', day, { delta: { ...zero, days: 1 } }, VIENNA)).toBe(false);
  });
});
