// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fakeGrid } from '../calendar/FakeGrid-test-support';
import type { SourceStatus } from '../extensions/types';
import { fetcherOf, occurrence, openCalendar } from './calendar-support';
import { act } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('../calendar/adapter/FullCalendarGrid', () => import('../calendar/FakeGrid-test-support'));

beforeEach(() => fakeGrid.reset());
afterEach(() => {
  document.body.innerHTML = '';
});

const status = (id: string, state: SourceStatus['status'], code: string | null = null) => ({
  id,
  calendar_id: 'c1',
  status: state,
  code,
});
const page = (sources: ReturnType<typeof status>[]) => ({
  items: [occurrence()],
  truncated: false,
  sources,
});
const sourceOptions = [
  { id: 'records:dates', label: 'Deadlines', color: '#aa0000' },
  { id: 'acme:talks', label: 'Talks' },
];

it('the status notice lists the sources that did not answer, by label', async () => {
  const { view } = await openCalendar({
    sources: sourceOptions,
    fetchOccurrences: fetcherOf(
      page([
        status('records:dates', 'timeout'),
        status('acme:talks', 'ok'),
        status('gone:x', 'not_installed'),
        status('acme:other', 'failed', 'raised'),
      ]),
    ),
  });
  const notices = [...document.querySelectorAll('[data-testid="source-status"] li')].map(
    (li) => li.textContent,
  );
  expect(notices).toHaveLength(3); // the ok one is not mentioned
  expect(notices[0]).toContain('Deadlines');
  expect(notices.join('|')).not.toContain('Talks');
  await view.unmount();
});

it('a label that is not known falls back to the id, and no code leaks into the words', async () => {
  const { view } = await openCalendar({
    sources: [],
    fetchOccurrences: fetcherOf(page([status('acme:other', 'failed', 'raised')])),
  });
  const notice = document.querySelector('[data-testid="source-status"]');
  expect(notice?.textContent).toContain('acme:other');
  expect(notice?.getAttribute('role')).toBe('status');
  await view.unmount();
});

it('shows no notice when every source answered', async () => {
  const { view } = await openCalendar({
    sources: sourceOptions,
    fetchOccurrences: fetcherOf(page([status('acme:talks', 'ok')])),
  });
  expect(document.querySelector('[data-testid="source-status"]')).toBeNull();
  await view.unmount();
});

it('the source filter sends source params', async () => {
  const { view, fetchOccurrences } = await openCalendar({ sources: sourceOptions });
  const box = [...document.querySelectorAll('label')].find((l) =>
    l.textContent?.includes('Deadlines'),
  );
  expect(box).toBeDefined();
  const first = fetchOccurrences.mock.calls[0]?.[0];
  expect(first?.sources).toEqual([]);
  await act(async () => (box as HTMLElement).querySelector('input')?.click());
  await act(async () => new Promise((r) => setTimeout(r, 10)));
  await act(async () =>
    fakeGrid.emitRange(
      { start: '2026-02-23T00:00:00Z', end: '2026-04-06T00:00:00Z' },
      'March 2026',
    ),
  );
  const last = fetchOccurrences.mock.calls.at(-1)?.[0];
  expect(last?.sources).toEqual(['records:dates']);
  await view.unmount();
});

it('no sources group when none is enabled', async () => {
  const { view } = await openCalendar({ sources: [] });
  expect(document.body.textContent).not.toContain('Sources');
  await view.unmount();
});

it('words the reason for a failure it knows, and says nothing for a plugin-only code', async () => {
  const { view } = await openCalendar({
    sources: sourceOptions,
    fetchOccurrences: fetcherOf(
      page([
        status('records:dates', 'failed', 'field_missing'),
        status('acme:other', 'failed', 'my_own_code'),
      ]),
    ),
  });
  const lines = [...document.querySelectorAll('[data-testid="source-status"] li')].map(
    (li) => li.textContent ?? '',
  );
  expect(lines[0]).toContain('A field it reads was deleted');
  expect(lines[1]).not.toContain('my_own_code');
  expect(lines[1]?.trim().endsWith('could not be loaded.')).toBe(true);
  await view.unmount();
});

it("a source's own cap is worded per source, not as the whole answer's 2,000", async () => {
  const { view } = await openCalendar({
    sources: sourceOptions,
    fetchOccurrences: fetcherOf({
      items: [occurrence()],
      truncated: true,
      sources: [status('records:dates', 'truncated')],
    }),
  });
  const text = document.body.textContent ?? '';
  expect(text).toContain('Showing the first 500 entries from Deadlines.');
  expect(text).not.toContain('first 2,000 items');
  await view.unmount();
});
