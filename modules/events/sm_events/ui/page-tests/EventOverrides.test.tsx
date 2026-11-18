// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { button, eventDetail, field, flush, refusal, stubFetch } from './support';
import { act, click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { default: EventEditor } = await import('../../pages/EventEditor');
const API = '/api/events/events';
const PREVIEW = '/api/events/recurrence/preview';
const props = {
  event_id: 'e1',
  calendar: { id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' },
  content_locales: ['en', 'de'],
  categories: [],
  default_timezone: 'Europe/Vienna',
};
const occurrence = {
  start: '2026-07-01T08:00:00Z',
  end: '2026-07-01T09:00:00Z',
  start_local: '2026-07-01T10:00',
  end_local: '2026-07-01T11:00',
};
const override = (extra = {}) => ({
  id: 9,
  original_start: '2026-07-08T08:00:00Z',
  kind: 'skipped',
  starts_at: null,
  ends_at: null,
  start_local: null,
  end_local: null,
  note: null,
  ...extra,
});
const series = (extra = {}) =>
  eventDetail({ rrule: 'FREQ=WEEKLY;BYDAY=WE', revision: 4, ...extra });
const preview = (orphaned: unknown[] = []) => ({
  occurrences: [occurrence],
  recurrence_until: null,
  orphaned,
});

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

async function open(routes: Record<string, unknown>) {
  const calls = stubFetch({
    [`GET ${API}/e1`]: () => series(),
    [`POST ${PREVIEW}`]: () => preview(),
    ...routes,
  });
  const view = await mount(<EventEditor {...props} />);
  await flush(450);
  return { calls, view };
}
const submitForm = async () => {
  await act(async () => {
    document
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
};
const label = '1 Jul 2026, 10:00';

describe('occurrence overrides', () => {
  it('previews the next occurrences in local time with the rule summary', async () => {
    const { view } = await open({});
    expect(view.host.textContent).toContain('Every week on Wednesday');
    expect(view.host.textContent).toContain(label);
    await view.unmount();
  });

  it('skip writes an override with the event revision, then reloads', async () => {
    const { calls, view } = await open({
      [`POST ${API}/e1/overrides`]: () => ({ ...override(), event_revision: 5 }),
    });
    await click(view.find(`[aria-label="Skip ${label}"]`));
    await flush();
    const post = calls.find((c) => c.url === `${API}/e1/overrides`);
    expect(post?.body).toEqual({
      expected_revision: 4,
      original_start: '2026-07-01T08:00:00Z',
      kind: 'skipped',
    });
    expect(calls.filter((c) => c.method === 'GET' && c.url === `${API}/e1`).length).toBe(2);
    await view.unmount();
  });

  it('cancel writes a cancelled override', async () => {
    const { calls, view } = await open({
      [`POST ${API}/e1/overrides`]: () => ({
        ...override({ kind: 'cancelled' }),
        event_revision: 5,
      }),
    });
    await click(view.find(`[aria-label="Cancel ${label}"]`));
    await flush();
    expect(calls.find((c) => c.url === `${API}/e1/overrides`)?.body).toMatchObject({
      kind: 'cancelled',
    });
    await view.unmount();
  });

  it('move dialog sends local times', async () => {
    const { calls, view } = await open({
      [`POST ${API}/e1/overrides`]: () => ({ ...override({ kind: 'moved' }), event_revision: 5 }),
    });
    await click(view.find(`[aria-label="Move ${label}"]`));
    expect(field('move-start').value).toBe('2026-07-01T10:00');
    await setValue(field('move-start'), '2026-07-02T09:30');
    await setValue(field('move-end'), '2026-07-02T10:30');
    await setValue(field('move-note'), 'Room taken');
    await act(async () => {
      document
        .querySelector('[role="dialog"] form')
        ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    await flush();
    expect(calls.find((c) => c.url === `${API}/e1/overrides`)?.body).toEqual({
      expected_revision: 4,
      original_start: '2026-07-01T08:00:00Z',
      kind: 'moved',
      start: '2026-07-02T09:30',
      end: '2026-07-02T10:30',
      note: 'Room taken',
    });
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    await view.unmount();
  });

  it('shows a move refusal at its field and keeps the dialog open', async () => {
    const { view } = await open({
      [`POST ${API}/e1/overrides`]: () => refusal(422, 'end_before_start'),
    });
    await click(view.find(`[aria-label="Move ${label}"]`));
    await act(async () => {
      document
        .querySelector('[role="dialog"] form')
        ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    await flush();
    expect(document.getElementById('move-end-error')?.textContent).toContain('after the start');
    expect(document.activeElement).toBe(field('move-end'));
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    await view.unmount();
  });

  it('restores an overridden occurrence', async () => {
    const { calls, view } = await open({
      [`GET ${API}/e1`]: () =>
        series({ overrides: [override({ original_start: occurrence.start })] }),
      [`DELETE ${API}/e1/overrides/9`]: null,
    });
    expect(view.host.textContent).toContain('Skipped');
    await click(view.find(`[aria-label="Restore ${label}"]`));
    await flush();
    expect(
      calls.some(
        (c) => c.method === 'DELETE' && c.url === `${API}/e1/overrides/9?expected_revision=4`,
      ),
    ).toBe(true);
    await view.unmount();
  });

  it('offers no overrides while the form has unsaved changes', async () => {
    const { view } = await open({});
    await setValue(field('text-en-title'), 'Changed');
    expect(view.host.textContent).toContain('Save your changes first');
    expect(view.find(`[aria-label="Skip ${label}"]`)?.hasAttribute('disabled')).toBe(true);
    await view.unmount();
  });

  it('a stale override reloads the event and says so, without retrying', async () => {
    const { calls, view } = await open({
      [`POST ${API}/e1/overrides`]: () => refusal(409, 'stale'),
    });
    await click(view.find(`[aria-label="Skip ${label}"]`));
    await flush();
    expect(view.find('[role="alert"]')?.textContent).toContain('Their version is loaded now');
    expect(calls.filter((c) => c.url === `${API}/e1/overrides`)).toHaveLength(1);
    await view.unmount();
  });
});

describe('changing the schedule of a series with overrides', () => {
  const withOverride = () => ({
    [`GET ${API}/e1`]: () => series({ overrides: [override()] }),
    [`PATCH ${API}/e1`]: () => series({ revision: 5 }),
  });

  it('orphaned overrides need confirmation', async () => {
    const { calls, view } = await open({
      ...withOverride(),
      [`POST ${PREVIEW}`]: () => preview([override()]),
    });
    await setValue(field('event-start'), '2026-07-01T11:00');
    await setValue(field('event-end'), '2026-07-01T12:00');
    await submitForm();
    const dialog = document.querySelector('[role="alertdialog"]');
    expect(dialog?.textContent).toContain('Changed occurrences will be removed');
    expect(dialog?.textContent).toContain('Skipped');
    await click(button('Cancel', dialog ?? document));
    await flush();
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false);
    await submitForm();
    await click(
      button('Save and remove them', document.querySelector('[role="alertdialog"]') ?? document),
    );
    await flush();
    const patch = calls.find((c) => c.method === 'PATCH')?.body as Record<string, unknown>;
    expect(patch.drop_orphaned_overrides).toBe(true);
    expect(patch.expected_revision).toBe(4);
    await view.unmount();
  });

  it('saves straight away when nothing is orphaned', async () => {
    const { calls, view } = await open(withOverride());
    await setValue(field('event-start'), '2026-07-01T11:00');
    await setValue(field('event-end'), '2026-07-01T12:00');
    await submitForm();
    const patch = calls.find((c) => c.method === 'PATCH')?.body as Record<string, unknown>;
    expect(patch.drop_orphaned_overrides).toBeUndefined();
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
    await view.unmount();
  });

  it('a 409 overrides_orphaned from the server opens the same confirmation', async () => {
    let asked = 0;
    const { calls, view } = await open({
      [`GET ${API}/e1`]: () => series({ overrides: [override()] }),
      [`PATCH ${API}/e1`]: () => refusal(409, 'overrides_orphaned'),
      [`POST ${PREVIEW}`]: () => {
        asked += 1;
        // After the submit: the pre-save check sees nothing orphaned, the ask after the 409 does.
        return preview(asked >= 2 ? [override()] : []);
      },
    });
    await setValue(field('event-start'), '2026-07-01T11:00');
    await setValue(field('event-end'), '2026-07-01T12:00');
    await flush(450);
    asked = 0;
    await submitForm();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain('removed');
    expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(1);
    await view.unmount();
  });
});
