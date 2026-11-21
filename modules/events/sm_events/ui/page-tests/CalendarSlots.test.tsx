// @vitest-environment happy-dom

import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fakeGrid } from '../calendar/FakeGrid-test-support';
import type { CalendarSlots } from '../calendar/types';
import { calendarInfo, fetcherOf, MARCH, occurrence, pageOf } from './calendar-support';
import { flush } from './support';
import { act, mount } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/FakeGrid-test-support'));
const { Calendar } = await import('../calendar/Calendar');

async function open(slots: CalendarSlots, items = [occurrence()]) {
  const view = await mount(
    <Calendar
      calendars={[calendarInfo()]}
      defaultTimezone="UTC"
      fetchOccurrences={fetcherOf(pageOf(items))}
      slots={slots}
    />,
  );
  await flush();
  await act(async () => fakeGrid.emitRange(MARCH, 'March 2026'));
  await flush();
  return view;
}

beforeEach(() => fakeGrid.reset());
afterEach(() => {
  document.body.innerHTML = '';
});

const Chip: NonNullable<CalendarSlots['EventChip']> = ({ occurrence: o, Default, ...rest }) =>
  o.type === 'x' ? (
    <b data-custom>custom {o.key}</b>
  ) : (
    <Default occurrence={o} Default={Default} {...rest} />
  );
const DetailSlot: NonNullable<CalendarSlots['Detail']> = ({
  occurrence: o,
  actions,
  Default,
  ...rest
}) => (
  <div data-testid="custom-detail">
    {o.title}
    <div data-testid="actions">{actions}</div>
    <Default occurrence={o} actions={null} {...rest} Default={Default} />
  </div>
);
const Start: NonNullable<CalendarSlots['ToolbarStart']> = ({ state }) => (
  <span data-testid="start">{state.view}</span>
);
const End: NonNullable<CalendarSlots['ToolbarEnd']> = ({ range }) => (
  <span data-testid="end">{range?.start}</span>
);

it('replaces the chip and falls back to Default per occurrence', async () => {
  const items = [occurrence({ key: 'a', type: 'x' }), occurrence({ key: 'b', title: 'Plain' })];
  const view = await open({ EventChip: Chip }, items);
  expect(document.querySelector('[data-key=a]')?.textContent).toBe('custom a');
  expect(document.querySelector('[data-key=b]')?.textContent).toContain('Plain');
  await view.unmount();
});

it('hands the detail slot its actions and a Default', async () => {
  const view = await open({ Detail: DetailSlot });
  await act(async () => fakeGrid.open('e1:0', document.body));
  const custom = document.querySelector('[data-testid=custom-detail]');
  expect(custom).not.toBeNull();
  expect(custom?.querySelector('[data-testid=actions] a')?.getAttribute('href')).toBe(
    '/admin/events/edit/e1',
  );
  expect(custom?.querySelector('[data-testid=calendar-detail]')).not.toBeNull();
  await view.unmount();
});

it('renders the toolbar slots at both ends with the state', async () => {
  const view = await open({ ToolbarStart: Start, ToolbarEnd: End });
  expect(document.querySelector('[data-testid=start]')?.textContent).toBe('month');
  expect(document.querySelector('[data-testid=end]')?.textContent).toBe(MARCH.start);
  await view.unmount();
});
