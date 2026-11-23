// @vitest-environment happy-dom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { usePreview } from '../hooks/usePreview';
import { type Call, flush, stubFetch } from './support';
import { mount } from './test-dom';

const RULE = 'FREQ=WEEKLY;BYDAY=TU';
const complete = {
  all_day: false,
  timezone: 'Europe/Vienna',
  start: '2026-12-01T10:00',
  end: '2026-12-01T11:00',
};
type Times = typeof complete;

function Probe({ times, incomplete }: { times: Times; incomplete?: boolean }) {
  const p = usePreview({ times, rrule: RULE, eventId: null, calendarId: 'c1', incomplete });
  return <div>{p.error ?? ''}</div>;
}

let calls: Call[] = [];
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

let shown = '';
async function asks(times: Times, incomplete = false): Promise<number> {
  calls = stubFetch({
    'POST /api/events/recurrence/preview': () => ({
      occurrences: [],
      recurrence_until: null,
      orphaned: [],
    }),
  });
  const view = await mount(<Probe times={times} incomplete={incomplete} />);
  await flush(500);
  shown = view.host.textContent ?? '';
  await view.unmount();
  return calls.length;
}

/** The server answers each of these with a 422; the form is only half filled. */
describe('the recurrence preview waits for inputs it can use', () => {
  it('asks once everything is there and valid', async () => {
    expect(await asks(complete)).toBe(1);
  });

  it('does not ask while the timezone is half typed', async () => {
    expect(await asks({ ...complete, timezone: 'Europe/Ber' })).toBe(0);
    expect(await asks({ ...complete, timezone: 'europe/berlin' })).toBe(0);
    expect(shown).toBe('Choose a timezone from the list, for example Europe/Vienna.');
  });

  it('asks for a zone the browser knows by another name, and for UTC', async () => {
    expect(await asks({ ...complete, timezone: 'UTC' })).toBe(1);
    expect(await asks({ ...complete, timezone: 'US/Eastern' })).toBe(1);
  });

  it('does not ask while the end is not after the start', async () => {
    expect(await asks({ ...complete, end: '2026-12-01T09:00' })).toBe(0);
    expect(await asks({ ...complete, end: complete.start })).toBe(0);
    expect(shown).toBe('The end must be after the start.'); // said at once, without a request
  });

  it('asks for an all-day event that ends on the day it starts', async () => {
    const day = { ...complete, all_day: true, start: '2026-12-01', end: '2026-12-01' };
    expect(await asks(day)).toBe(1);
    expect(await asks({ ...day, end: '2026-11-30' })).toBe(0);
  });

  it('does not ask while "ends on a date" has no date yet', async () => {
    expect(await asks(complete, true)).toBe(0);
    expect(shown).toBe(''); // nothing to say until the date is chosen
  });
});
