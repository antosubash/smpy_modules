// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { eventDetail, flush, refusal, stubFetch } from './support';
import { click, mount } from './test-dom';

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

const open = async (extra = {}, routes: Record<string, unknown> = {}) => {
  stubFetch({
    [`GET ${API}/e1`]: () => eventDetail({ revision: 4, can_publish: true, ...extra }),
    ...routes,
  });
  const view = await mount(<EventEditor {...props} />);
  await flush();
  return { view };
};

describe('revision history', () => {
  const revisions = [
    { number: 1, action: 'created', actor: 'u1', created_at: '2026-06-01T10:00:00Z', note: null },
    {
      number: 3,
      action: 'rejected',
      actor: 'u2',
      created_at: '2026-06-03T10:00:00Z',
      note: 'Add the room',
    },
    { number: 2, action: 'submitted', actor: null, created_at: '2026-06-02T10:00:00Z', note: null },
  ];
  it('lists revisions newest first with actor, time and note', async () => {
    const { view } = await open(
      {},
      {
        [`GET ${API}/e1/revisions`]: () => revisions,
        [`GET ${API}/e1/revisions/3`]: () => ({
          ...revisions[1],
          snapshot: {
            status: 'draft',
            timezone: 'Europe/Vienna',
            starts_at: '2026-07-01T08:00:00Z',
            ends_at: '2026-07-01T09:00:00Z',
            texts: { en: { title: 'Concert v3' } },
          },
        }),
      },
    );
    await click(view.button('History'));
    await flush();
    const rows = [...document.querySelectorAll('[role="dialog"] ol > li')];
    expect(rows.map((r) => r.querySelector('strong')?.textContent)).toEqual([
      'Revision 3',
      'Revision 2',
      'Revision 1',
    ]);
    expect(rows[0]?.textContent).toContain('Rejected');
    expect(rows[0]?.textContent).toContain('Add the room');
    expect(rows[0]?.textContent).toContain('A team member');
    expect(rows[1]?.textContent).toContain('System');
    expect(rows[0]?.textContent).toContain('3 Jun 2026, 12:00');
    await click(document.querySelector('[aria-label="View revision 3"]'));
    await flush();
    expect(document.querySelector('[role="dialog"] dl')?.textContent).toContain('Concert v3');
    expect(document.querySelector('[role="dialog"] dl')?.textContent).toContain('Draft');
    await view.unmount();
  });

  it('shows a failure, not an empty history', async () => {
    const { view } = await open({}, { [`GET ${API}/e1/revisions`]: () => refusal(500, 'x') });
    await click(view.button('History'));
    await flush();
    const dialog = document.querySelector('[role="dialog"]');
    expect(dialog?.querySelector('[role="alert"]')?.textContent).toContain('The request failed');
    expect(dialog?.textContent).not.toContain('No history yet.');
    await view.unmount();
  });
});
