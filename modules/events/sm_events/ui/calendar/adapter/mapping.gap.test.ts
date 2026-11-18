import { describe, expect, it } from 'vitest';
import { acceptsSelection, chipFor, skipsWallTime, toSlot } from './mapping';

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

describe('chipFor on the repeated hour', () => {
  const fold = {
    extendedProps: {
      occurrence: {
        start: '2026-10-25T00:30:00Z',
        end: '2026-10-25T01:00:00Z',
        all_day: false,
      },
    },
  };
  it('replaces the library text that reads backwards', () => {
    const shown = chipFor(fold, '2:30 – 2:00AM', (_o, text) => text, 'Europe/Vienna', 'en');
    expect(shown).toMatch(/GMT\+2/);
    expect(shown).toMatch(/GMT\+1/);
  });
  it('keeps the library text elsewhere', () => {
    const plain = {
      extendedProps: {
        occurrence: {
          ...fold.extendedProps.occurrence,
          end: '2026-10-25T01:30:00Z',
          start: '2026-10-25T00:30:00Z',
        },
      },
    };
    expect(chipFor(plain, '2:30 – 3:30', (_o, text) => text, 'UTC', 'en')).toBe('2:30 – 3:30');
  });
});

describe('acceptsSelection', () => {
  const editing = (canCreate: boolean, pending: string[]) => ({
    canCreate,
    onCreate: () => {},
    onChange: async () => true,
    onMove: () => {},
    pendingKeys: new Set(pending),
  });
  it('needs a writable calendar shown and no write in flight', () => {
    expect(acceptsSelection(editing(true, []))).toBe(true);
    expect(acceptsSelection(editing(false, []))).toBe(false);
    expect(acceptsSelection(editing(true, ['e1:0']))).toBe(false);
    expect(acceptsSelection(undefined)).toBe(false);
  });
});

describe('toSlot on the skipped hour', () => {
  it('flags a selection that runs backwards once the library resolved its start forward', () => {
    const at = (iso: string) => new Date(iso);
    const slot = toSlot({
      start: at('2026-03-29T01:30:00Z'), // the 02:30 slot, moved to 03:30
      end: at('2026-03-29T01:00:00Z'), // its end, 03:00, was a real time
      allDay: false,
      startStr: '2026-03-29T03:30:00+02:00',
      endStr: '2026-03-29T03:00:00+02:00',
    });
    expect(slot.skipped).toBe(true);
  });
});
