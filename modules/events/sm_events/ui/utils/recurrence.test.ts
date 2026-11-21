import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  buildRule,
  COUNT_MAX,
  INTERVAL_MAX,
  isCustom,
  monthlyChoices,
  parseRule,
  RRULE_MAX_LEN,
  type RuleForm,
  summarise,
} from './recurrence';

// A Monday, the 2nd of March 2026, and the last Friday of December 2026.
const MONDAY = '2026-03-02T10:00';
const LAST_FRIDAY = '2026-12-25T10:00';
const FORMS: [string, RuleForm, string][] = [
  [
    'daily',
    { freq: 'DAILY', interval: 1, byDay: [], monthly: { mode: 'day' }, end: { kind: 'never' } },
    MONDAY,
  ],
  [
    'weekly with count',
    {
      freq: 'WEEKLY',
      interval: 2,
      byDay: ['MO', 'WE'],
      monthly: { mode: 'day' },
      end: { kind: 'count', count: 10 },
    },
    MONDAY,
  ],
  [
    'monthly by day until a date',
    {
      freq: 'MONTHLY',
      interval: 1,
      byDay: [],
      monthly: { mode: 'day' },
      end: { kind: 'until', date: '2026-12-31' },
    },
    MONDAY,
  ],
  [
    'monthly on the first weekday',
    {
      freq: 'MONTHLY',
      interval: 3,
      byDay: [],
      monthly: { mode: 'nth', nth: 1 },
      end: { kind: 'never' },
    },
    MONDAY,
  ],
  [
    'monthly on the last weekday',
    {
      freq: 'MONTHLY',
      interval: 2,
      byDay: [],
      monthly: { mode: 'nth', nth: -1 },
      end: { kind: 'until', date: '2026-12-31' },
    },
    LAST_FRIDAY,
  ],
  [
    'yearly',
    {
      freq: 'YEARLY',
      interval: 1,
      byDay: [],
      monthly: { mode: 'day' },
      end: { kind: 'count', count: 3 },
    },
    MONDAY,
  ],
];

describe('recurrence rules', () => {
  it.each(FORMS)('round-trips %s', (_name, form, start) => {
    expect(parseRule(buildRule(form, start), start)).toEqual(form);
  });

  it('builds the rule text the server normalises', () => {
    const weekly: RuleForm = { ...FORMS[1][1] };
    expect(buildRule(weekly, MONDAY)).toBe('FREQ=WEEKLY;INTERVAL=2;COUNT=10;BYDAY=MO,WE');
    expect(buildRule(FORMS[4][1], LAST_FRIDAY)).toBe(
      'FREQ=MONTHLY;INTERVAL=2;UNTIL=20261231;BYDAY=-1FR',
    );
  });

  it('weekly always includes the start weekday', () => {
    const form: RuleForm = {
      freq: 'WEEKLY',
      interval: 1,
      byDay: ['WE', 'FR'],
      monthly: { mode: 'day' },
      end: { kind: 'never' },
    };
    expect(buildRule(form, MONDAY)).toBe('FREQ=WEEKLY;BYDAY=MO,WE,FR');
    expect(buildRule({ ...form, byDay: [] }, MONDAY)).toBe('FREQ=WEEKLY;BYDAY=MO');
  });

  it('unknown parts become custom', () => {
    const raw = 'FREQ=MONTHLY;BYMONTHDAY=1,15;BYSETPOS=1';
    expect(parseRule(raw, MONDAY)).toEqual({ custom: raw });
    expect(parseRule('FREQ=MONTHLY;BYMONTHDAY=15', MONDAY)).toEqual({
      custom: 'FREQ=MONTHLY;BYMONTHDAY=15',
    });
    expect(parseRule('FREQ=WEEKLY;BYDAY=2MO', MONDAY)).toEqual({ custom: 'FREQ=WEEKLY;BYDAY=2MO' });
  });

  it('reads an empty rule as no recurrence and strips a prefix', () => {
    expect(parseRule(null, MONDAY)).toBeNull();
    expect(parseRule('', MONDAY)).toBeNull();
    expect(parseRule('RRULE:FREQ=DAILY', MONDAY)).toMatchObject({ freq: 'DAILY' });
  });

  it('turns a stored UTC until back into the event-timezone date', () => {
    const rule = 'FREQ=DAILY;UNTIL=20270101T045959Z';
    expect(parseRule(rule, MONDAY, 'America/New_York')).toMatchObject({
      end: { kind: 'until', date: '2026-12-31' },
    });
  });

  it('offers only the monthly choices the start satisfies', () => {
    expect(monthlyChoices('2026-03-02T10:00')).toEqual({ day: 2, nth: 1, last: false });
    expect(monthlyChoices('2026-12-25T10:00')).toEqual({ day: 25, nth: 4, last: true });
    expect(monthlyChoices('2026-03-31T10:00')).toEqual({ day: 31, nth: undefined, last: true });
  });
});

describe('summaries in en', () => {
  it('reads a weekly rule', () => {
    const weekly: RuleForm = { ...FORMS[1][1], interval: 1 };
    expect(summarise(weekly, MONDAY)).toBe('Every week on Monday and Wednesday, 10 times');
  });
  it('reads a monthly rule with an end date', () => {
    expect(summarise(FORMS[4][1], LAST_FRIDAY)).toBe(
      'Every 2 months on the last Friday, until 31 Dec 2026',
    );
  });
  it('reads daily, monthly by day and yearly rules', () => {
    expect(summarise(FORMS[0][1], MONDAY)).toBe('Every day');
    expect(summarise(FORMS[2][1], MONDAY)).toBe('Every month on day 2, until 31 Dec 2026');
    expect(summarise(FORMS[5][1], MONDAY)).toBe('Every year, 3 times');
  });
  it('shows a custom rule as it is', () => {
    expect(summarise({ custom: 'FREQ=DAILY;BYSETPOS=1' }, MONDAY)).toBe(
      'Custom rule: FREQ=DAILY;BYSETPOS=1',
    );
  });
});

describe('the rule editor never rewrites what it cannot express', () => {
  it.each(FORMS)('build(parse(rule)) is the rule for %s', (_name, form, start) => {
    const rule = buildRule(form, start);
    const parsed = parseRule(rule, start);
    expect(parsed && !isCustom(parsed)).toBe(true);
    expect(buildRule(parsed as RuleForm, start)).toBe(rule);
  });

  it('a form with the end date cleared builds no empty part and stays a form', () => {
    for (const [, form, start] of FORMS) {
      const rule = buildRule({ ...form, end: { kind: 'until', date: '' } }, start);
      expect(rule).not.toMatch(/UNTIL|=(;|$)/);
      const parsed = parseRule(rule, start);
      expect(parsed && !isCustom(parsed)).toBe(true);
    }
  });

  it('every rule the editor builds from any end, interval and weekday set parses as a form', () => {
    const ends: RuleForm['end'][] = [
      { kind: 'never' },
      { kind: 'count', count: 1 },
      { kind: 'count', count: COUNT_MAX },
      { kind: 'until', date: '2026-12-31' },
      { kind: 'until', date: '' },
    ];
    for (const freq of ['DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'] as const) {
      for (const end of ends) {
        for (const interval of [1, 2, INTERVAL_MAX]) {
          const form: RuleForm = { freq, interval, byDay: ['WE'], monthly: { mode: 'day' }, end };
          const rule = buildRule(form, MONDAY);
          const parsed = parseRule(rule, MONDAY);
          expect(parsed && !isCustom(parsed), rule).toBe(true);
          expect(buildRule(parsed as RuleForm, MONDAY)).toBe(rule);
        }
      }
    }
  });

  const INEXPRESSIBLE = [
    'FREQ=MONTHLY;BYMONTHDAY=1,15;BYSETPOS=1',
    'FREQ=DAILY;INTERVAL=100',
    'FREQ=DAILY;INTERVAL=0',
    'FREQ=DAILY;COUNT=731',
    'FREQ=DAILY;COUNT=0',
    'FREQ=DAILY;COUNT=3;UNTIL=20271231',
    'FREQ=WEEKLY;BYDAY=2MO',
    'FREQ=MONTHLY;BYMONTHDAY=15',
    'FREQ=DAILY;UNTIL=',
    'FREQ=HOURLY',
    'FREQ=YEARLY;BYMONTH=3',
  ];
  it.each(INEXPRESSIBLE)('keeps %s as custom text, byte for byte', (rule) => {
    expect(parseRule(rule, MONDAY)).toEqual({ custom: rule });
  });

  it('agrees with the backend limits', () => {
    const python = readFileSync(
      new URL('../../core/constants/__init__.py', import.meta.url),
      'utf8',
    );
    const read = (name: string) => Number(new RegExp(`^${name} = (\\d+)`, 'm').exec(python)?.[1]);
    expect(RRULE_MAX_LEN).toBe(read('RRULE_MAX_LEN'));
    expect(INTERVAL_MAX).toBe(read('RRULE_MAX_INTERVAL'));
    expect(COUNT_MAX).toBe(read('RRULE_MAX_COUNT'));
  });
});
