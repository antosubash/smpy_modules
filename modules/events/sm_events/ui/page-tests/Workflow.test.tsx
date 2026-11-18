// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { workflowActions } from '../components/editor/WorkflowBar';
import { eventDetail, field, flush, refusal, stubFetch } from './support';
import { act, click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { default: EventEditor } = await import('../../pages/EventEditor');
const API = '/api/events/events';
const props = {
  event_id: 'e1',
  calendar: { id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' },
  content_locales: ['en', 'de'],
  categories: [],
  default_timezone: 'Europe/Vienna',
};

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

describe('workflow actions', () => {
  const cases: [string, boolean, string, boolean, string[]][] = [
    // status, scheduled, publisher?, writes?, expected
    ['draft', false, 'writer', true, ['submit']],
    ['draft', false, 'publisher', true, ['submit', 'approve']],
    ['in_review', false, 'writer', true, ['withdraw']],
    ['in_review', false, 'publisher', true, ['withdraw', 'approve', 'reject']],
    ['draft', true, 'writer', true, []],
    ['draft', true, 'publisher', true, ['unschedule']],
    ['in_review', true, 'publisher', true, ['unschedule']],
    ['published', false, 'writer', true, []],
    ['published', false, 'publisher', true, ['unpublish']],
    ['draft', false, 'viewer', false, []],
  ];
  it.each(cases)('%s (scheduled %s) for a %s', (status, scheduled, who, write, expected) => {
    const found = workflowActions({
      status: status as 'draft',
      scheduled,
      can_write: write,
      can_publish: who === 'publisher',
    });
    expect(found).toEqual(expected);
  });
});

describe('workflow actions for every combination of rights', () => {
  // [status, scheduled] -> actions for (write, publish) = (no, no), (no, yes), (yes, no), (yes, yes)
  const table: [string, boolean, string[][]][] = [
    ['draft', false, [[], [], ['submit'], ['submit', 'approve']]],
    ['in_review', false, [[], [], ['withdraw'], ['withdraw', 'approve', 'reject']]],
    ['published', false, [[], [], [], ['unpublish']]],
    ['draft', true, [[], [], [], ['unschedule']]],
    ['in_review', true, [[], [], [], ['unschedule']]],
  ];
  const rights: [boolean, boolean][] = [
    [false, false],
    [false, true],
    [true, false],
    [true, true],
  ];
  for (const [status, scheduled, expected] of table) {
    rights.forEach(([write, publish], index) => {
      it(`${status}${scheduled ? ' (scheduled)' : ''}, write ${write}, publish ${publish}`, () => {
        expect(
          workflowActions({
            status: status as 'draft',
            scheduled,
            can_write: write,
            can_publish: publish,
          }),
        ).toEqual(expected[index]);
      });
    });
  }
});

const open = async (extra = {}, routes: Record<string, unknown> = {}) => {
  const calls = stubFetch({
    [`GET ${API}/e1`]: () => eventDetail({ revision: 4, can_publish: true, ...extra }),
    ...routes,
  });
  const view = await mount(<EventEditor {...props} />);
  await flush();
  return { calls, view };
};
const names = (view: { all: <T extends Element>(s: string) => T[] }) =>
  view.all('section[aria-label="Publishing"] button').map((b) => b.textContent);

describe('workflow bar', () => {
  it('shows only the actions the caller may take', async () => {
    const { view } = await open({ status: 'in_review' });
    expect(names(view)).toEqual(['Withdraw from review', 'Approve…', 'Reject…']);
    await view.unmount();
    const writer = await open({ status: 'draft', can_publish: false });
    expect(names(writer.view)).toEqual(['Submit for review']);
    await writer.view.unmount();
  });

  it('shows the status and a schedule, with its time on the event clock', async () => {
    const { view } = await open({ scheduled: true, publish_at: '2026-12-01T08:30:00Z' });
    const bar = view.find('section[aria-label="Publishing"]');
    expect(bar?.textContent).toContain('Scheduled');
    expect(bar?.textContent).toContain('1 Dec 2026, 09:30');
    expect(names(view)).toEqual(['Cancel the schedule']);
    await view.unmount();
  });

  it('submit sends the event revision and shows the new state', async () => {
    const { calls, view } = await open(
      { status: 'draft' },
      {
        [`POST ${API}/e1/submit`]: () =>
          eventDetail({ revision: 5, status: 'in_review', can_publish: true }),
      },
    );
    await click(view.button('Submit for review'));
    await flush();
    expect(calls.find((c) => c.url === `${API}/e1/submit`)?.body).toEqual({ expected_revision: 4 });
    expect(names(view)).toContain('Withdraw from review');
    await view.unmount();
  });

  it('approve now sends no time', async () => {
    const { calls, view } = await open(
      { status: 'in_review' },
      {
        [`POST ${API}/e1/approve`]: () =>
          eventDetail({ revision: 5, status: 'published', can_publish: true }),
      },
    );
    await click(view.button('Approve…'));
    await act(async () => {
      document
        .querySelector('[role="dialog"] form')
        ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    await flush();
    expect(calls.find((c) => c.url === `${API}/e1/approve`)?.body).toEqual({
      expected_revision: 4,
    });
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    await view.unmount();
  });

  it('approve later sends publish_at_local as typed', async () => {
    const { calls, view } = await open(
      { status: 'draft' },
      {
        [`POST ${API}/e1/approve`]: () =>
          eventDetail({
            revision: 5,
            scheduled: true,
            publish_at: '2026-12-01T08:30:00Z',
            can_publish: true,
          }),
      },
    );
    await click(view.button('Approve…'));
    await setValue(field('schedule-when'), 'later');
    await setValue(field('schedule-at'), '2026-12-01T09:30');
    await act(async () => {
      document
        .querySelector('[role="dialog"] form')
        ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    await flush();
    expect(calls.find((c) => c.url === `${API}/e1/approve`)?.body).toEqual({
      expected_revision: 4,
      publish_at_local: '2026-12-01T09:30',
    });
    await view.unmount();
  });

  it('a time that does not exist shows at the field and keeps the dialog', async () => {
    const { view } = await open(
      { status: 'draft' },
      { [`POST ${API}/e1/approve`]: () => refusal(422, 'invalid_local_time') },
    );
    await click(view.button('Approve…'));
    await setValue(field('schedule-when'), 'later');
    await setValue(field('schedule-at'), '2026-03-29T02:30');
    await act(async () => {
      document
        .querySelector('[role="dialog"] form')
        ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    await flush();
    expect(document.getElementById('schedule-at-error')?.textContent).toContain('does not exist');
    expect(document.activeElement).toBe(field('schedule-at'));
    await view.unmount();
  });

  it('reject requires a note', async () => {
    const { calls, view } = await open(
      { status: 'in_review' },
      { [`POST ${API}/e1/reject`]: () => eventDetail({ revision: 5, can_publish: true }) },
    );
    await click(view.button('Reject…'));
    const submit = () =>
      act(async () => {
        document
          .querySelector('[role="dialog"] form')
          ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      });
    await submit();
    await flush();
    expect(document.getElementById('reject-note-error')?.textContent).toBe(
      'This field is required.',
    );
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    await setValue(field('reject-note'), 'Add the room');
    await submit();
    await flush();
    expect(calls.find((c) => c.url === `${API}/e1/reject`)?.body).toEqual({
      expected_revision: 4,
      note: 'Add the room',
    });
    await view.unmount();
  });

  it('waits for unsaved edits', async () => {
    const { view } = await open({ status: 'draft' });
    await setValue(field('text-en-title'), 'Changed');
    expect(view.host.textContent).toContain('Save or discard your changes');
    expect(view.button('Approve…')?.hasAttribute('disabled')).toBe(true);
    await view.unmount();
  });

  it('a refused transition says what happened, and a stale one reloads', async () => {
    const { view } = await open(
      { status: 'draft' },
      { [`POST ${API}/e1/submit`]: () => refusal(409, 'invalid_transition') },
    );
    await click(view.button('Submit for review'));
    await flush();
    expect(view.find('[role="alert"]')?.textContent).toContain('not available in the event');
    await view.unmount();
    const stale = await open(
      { status: 'draft' },
      { [`POST ${API}/e1/submit`]: () => refusal(409, 'stale') },
    );
    await click(stale.view.button('Submit for review'));
    await flush();
    expect(stale.view.find('[role="alert"]')?.textContent).toContain('Their version is loaded now');
    await stale.view.unmount();
  });

  it('locked banner disables form for non-publisher', async () => {
    const { view } = await open({
      status: 'draft',
      scheduled: true,
      locked: true,
      can_publish: false,
    });
    expect(view.host.textContent).toContain('Scheduled: only a publisher can change it.');
    expect(field('text-en-title').disabled).toBe(true);
    expect(names(view)).toEqual([]);
    await view.unmount();
  });
});
