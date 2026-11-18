import { describe, expect, it } from 'vitest';
import type { Occurrence } from '../../utils/types-events';
import type { CalendarEditing } from '../types';
import {
  allowDrop,
  chipFor,
  occurrenceOf,
  skipsWallTime,
  toChange,
  toEventInput,
  toRangeChange,
  toSlot,
  VIEW_NAMES,
  viewOfName,
} from './mapping';

const base: Occurrence = {
  source: 'events',
  key: 'e1:0',
  calendar_id: 'c1',
  start: '2026-03-23T09:00:00Z',
  end: '2026-03-23T10:00:00Z',
  all_day: false,
  timezone: 'Europe/Vienna',
  start_date: null,
  end_date: null,
  title: 'Talk <b>1</b>',
  lang: 'en',
  color: '#2563eb',
  url: '/p/talk',
  status: 'confirmed',
  type: 'event',
  editable: true,
  event_id: 'e1',
  original_start: null,
  event_status: 'published',
};
const editing = (pending: string[] = []): CalendarEditing => ({
  canCreate: true,
  onCreate: () => {},
  onChange: async () => true,
  onMove: () => {},
  pendingKeys: new Set(pending),
});

describe('toEventInput', () => {
  it('uses dates and no zone for an all-day occurrence', () => {
    const input = toEventInput(
      { ...base, all_day: true, start_date: '2026-03-29', end_date: '2026-03-30' },
      undefined,
    );
    expect(input).toMatchObject({ start: '2026-03-29', end: '2026-03-30', allDay: true });
  });
  it('uses instants for a timed one, keeps the title as plain text and the url out of the event', () => {
    const input = toEventInput(base, undefined);
    expect(input).toMatchObject({
      id: 'e1:0',
      start: '2026-03-23T09:00:00Z',
      end: '2026-03-23T10:00:00Z',
      allDay: false,
      title: 'Talk <b>1</b>',
      interactive: true,
    });
    expect(input.url).toBeUndefined();
    expect(input.extendedProps?.occurrence).toEqual(base);
  });

  const cases: [string, Partial<Occurrence>, CalendarEditing | undefined, boolean][] = [
    ['no editing prop', {}, undefined, false],
    ['editable', {}, editing(), true],
    ['not editable', { editable: false }, editing(), false],
    ['cancelled', { status: 'cancelled' }, editing(), false],
    ['pending', {}, editing(['e1:0']), false],
    ['draft stays draggable', { event_status: 'draft' }, editing(), true],
    ['in review stays draggable', { event_status: 'in_review' }, editing(), true],
  ];
  it.each(cases)('editable truth table: %s', (_name, patch, edit, expected) => {
    const input = toEventInput({ ...base, ...patch }, edit);
    expect(input.startEditable).toBe(expected);
    expect(input.durationEditable).toBe(expected);
  });

  it('marks draft, review, cancelled and pending with classes, and published with none', () => {
    const classes = (patch: Partial<Occurrence>, edit?: CalendarEditing) =>
      toEventInput({ ...base, ...patch }, edit).className;
    expect(classes({ event_status: 'draft' })).toContain('sm-ev-draft');
    expect(classes({ event_status: 'in_review' })).toContain('sm-ev-review');
    expect(classes({ status: 'cancelled' })).toContain('sm-ev-cancelled');
    expect(classes({}, editing(['e1:0']))).toContain('sm-ev-pending');
    expect(classes({})).toBeUndefined();
  });
});

describe('toChange', () => {
  it('encodes a timed change as instants', () => {
    const change = toChange('move', base, {
      start: new Date('2026-03-30T09:00:00Z'),
      end: new Date('2026-03-30T10:00:00Z'),
      allDay: false,
      startStr: '2026-03-30T05:00:00-04:00',
      endStr: '2026-03-30T06:00:00-04:00',
    });
    expect(change).toEqual({
      occurrence: base,
      kind: 'move',
      start: '2026-03-30T09:00:00Z',
      end: '2026-03-30T10:00:00Z',
      allDay: false,
    });
  });
  it('encodes an all-day change as dates with an exclusive end', () => {
    const all = { ...base, all_day: true, start_date: '2026-03-29', end_date: '2026-03-30' };
    const change = toChange('move', all, {
      start: new Date('2026-03-31T00:00:00Z'),
      end: new Date('2026-04-01T00:00:00Z'),
      allDay: true,
      startStr: '2026-03-31',
      endStr: '2026-04-01',
    });
    expect(change).toMatchObject({ start: '2026-03-31', end: '2026-04-01', allDay: true });
  });
  it('treats a missing all-day end as one day', () => {
    const all = { ...base, all_day: true, start_date: '2026-03-29', end_date: '2026-03-30' };
    const change = toChange('move', all, {
      start: new Date('2026-03-31T00:00:00Z'),
      end: null,
      allDay: true,
      startStr: '2026-03-31',
      endStr: '',
    });
    expect(change.end).toBe('2026-04-01');
  });
  it('keeps the old duration when a timed end is missing', () => {
    const change = toChange('move', base, {
      start: new Date('2026-03-30T09:00:00Z'),
      end: null,
      allDay: false,
      startStr: '',
      endStr: '',
    });
    expect(change.end).toBe('2026-03-30T10:00:00Z');
  });
});

describe('allowDrop', () => {
  it('refuses a drop that would change all-day', () => {
    expect(allowDrop(base, false)).toBe(true);
    expect(allowDrop(base, true)).toBe(false);
    expect(allowDrop({ ...base, all_day: true }, true)).toBe(true);
    expect(allowDrop({ ...base, all_day: true }, false)).toBe(false);
  });
});

describe('views and ranges', () => {
  it('maps every view both ways', () => {
    expect(VIEW_NAMES).toEqual({
      month: 'dayGridMonth',
      week: 'timeGridWeek',
      day: 'timeGridDay',
      list: 'listMonth',
    });
    for (const [view, name] of Object.entries(VIEW_NAMES)) expect(viewOfName(name)).toBe(view);
    expect(viewOfName('multiMonthYear')).toBe('month');
  });
  it('turns datesSet into a range in the grid zone', () => {
    const change = toRangeChange(
      {
        start: new Date('2026-03-29T22:00:00Z'),
        end: new Date('2026-05-10T22:00:00Z'),
        view: {
          type: 'dayGridMonth',
          title: 'April 2026',
          currentStart: new Date('2026-03-31T22:00:00Z'),
        },
      },
      'Europe/Vienna',
    );
    expect(change).toEqual({
      visible: { start: '2026-03-29T22:00:00Z', end: '2026-05-10T22:00:00Z' },
      title: 'April 2026',
      view: 'month',
      date: '2026-04-01',
    });
  });
  it('reads the occurrence back off an event', () => {
    expect(occurrenceOf({ extendedProps: { occurrence: base } })).toBe(base);
  });
});

describe('toEventInput with an optimistic placement', () => {
  it('shows a timed occurrence where the user dropped it', () => {
    const input = toEventInput(base, editing(['e1:0']), {
      start: '2026-03-30T09:00:00Z',
      end: '2026-03-30T10:00:00Z',
    });
    expect(input).toMatchObject({
      start: '2026-03-30T09:00:00Z',
      end: '2026-03-30T10:00:00Z',
      startEditable: false,
    });
  });
  it('shows an all-day occurrence on the dropped dates', () => {
    const allDay = { ...base, all_day: true, start_date: '2026-03-29', end_date: '2026-03-30' };
    const input = toEventInput(allDay, editing(), { start: '2026-03-31', end: '2026-04-01' });
    expect(input).toMatchObject({ start: '2026-03-31', end: '2026-04-01', allDay: true });
  });
});

describe('toSlot', () => {
  const sel = (
    start: string,
    end: string | null,
    allDay = false,
    startStr = start,
    endStr = end ?? '',
  ) => ({
    start: new Date(start),
    end: end ? new Date(end) : null,
    allDay,
    startStr,
    endStr,
  });
  it('keeps a dragged timed range as instants', () => {
    expect(toSlot(sel('2026-07-01T08:00:00Z', '2026-07-01T10:30:00Z'))).toEqual({
      allDay: false,
      start: '2026-07-01T08:00:00Z',
      end: '2026-07-01T10:30:00Z',
    });
  });
  it('turns a click on one 30-minute slot into a 60-minute event', () => {
    expect(toSlot(sel('2026-07-01T08:00:00Z', '2026-07-01T08:30:00Z'))).toMatchObject({
      end: '2026-07-01T09:00:00Z',
    });
  });
  it('gives a click that carries no end the default length', () => {
    expect(toSlot(sel('2026-07-01T08:00:00Z', null))).toMatchObject({
      end: '2026-07-01T09:00:00Z',
    });
  });
  it('keeps all-day dates and an exclusive end', () => {
    expect(toSlot(sel('2026-08-01', '2026-08-04', true, '2026-08-01', '2026-08-04'))).toEqual({
      allDay: true,
      start: '2026-08-01',
      end: '2026-08-04',
    });
  });
  it('makes a one-day click on the day grid one day long', () => {
    expect(toSlot(sel('2026-08-01', null, true, '2026-08-01', ''))).toEqual({
      allDay: true,
      start: '2026-08-01',
      end: '2026-08-02',
    });
  });
});

describe('chipFor', () => {
  it('renders an occurrence through the chip', () => {
    const render = (o: Occurrence, text: string) => `${o.key}@${text}`;
    expect(chipFor({ extendedProps: { occurrence: base } }, '9:00', render)).toBe('e1:0@9:00');
  });
  it('leaves the selection mirror and the drag helper (no occurrence) to the library', () => {
    expect(chipFor({ extendedProps: {} }, '9:00', () => 'chip')).toBeUndefined();
  });
});

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
