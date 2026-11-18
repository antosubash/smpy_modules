// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { type Call, eventDetail, field, flush, refusal, stubFetch } from './support';
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
const theirs = () =>
  eventDetail({
    revision: 5,
    venue_name: 'Their hall',
    texts: {
      en: {
        slug: 'concert',
        title: 'Theirs',
        summary: null,
        description: '',
        seo_title: null,
        seo_description: null,
        noindex: false,
      },
    },
  });

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

async function conflict(patch: () => unknown = () => refusal(409, 'stale')) {
  let loads = 0;
  const calls = stubFetch({
    [`GET ${API}/e1`]: () => (loads++ === 0 ? eventDetail({ revision: 4 }) : theirs()),
    [`PATCH ${API}/e1`]: patch,
  });
  const view = await mount(<EventEditor {...props} />);
  await flush();
  await setValue(field('text-en-title'), 'Mine');
  await act(async () => {
    document
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
  return { calls, view };
}
const patches = (calls: Call[]) => calls.filter((c) => c.method === 'PATCH');

describe('stale save', () => {
  it('409 stale shows panel with differing fields', async () => {
    const { view } = await conflict();
    const panel = view.find('section[aria-label="Someone else saved this event first"]');
    expect(panel).not.toBeNull();
    const rows = [...(panel?.querySelectorAll('tbody tr') ?? [])].map((r) =>
      [...r.querySelectorAll('td')].map((c) => c.textContent),
    );
    expect(rows).toContainEqual(['Title (English)', 'Theirs', 'Mine']);
    expect(rows).toContainEqual(['Venue', 'Their hall', '(empty)']);
    expect(panel?.querySelector('[role="alert"]')?.textContent).toContain('Someone else saved');
    expect(field('text-en-title').value).toBe('Mine'); // the unsaved edit is kept
    await view.unmount();
  });

  it('no silent retry', async () => {
    const { calls, view } = await conflict();
    await flush(200);
    expect(patches(calls)).toHaveLength(1);
    await view.unmount();
  });

  it('load theirs discards my edits', async () => {
    const { calls, view } = await conflict();
    await click(view.button('Load their version'));
    expect(field('text-en-title').value).toBe('Theirs');
    expect(view.find('section[aria-label="Someone else saved this event first"]')).toBeNull();
    expect(patches(calls)).toHaveLength(1);
    expect(view.button('Save')?.hasAttribute('disabled')).toBe(true);
    await view.unmount();
  });

  it('save mine resends with the new revision, only on the click', async () => {
    let n = 0;
    const { calls, view } = await conflict(() =>
      n++ === 0 ? refusal(409, 'stale') : eventDetail({ revision: 6 }),
    );
    await click(view.button('Save mine over theirs'));
    await flush();
    type Sent = {
      expected_revision: number;
      texts: { en: { title: string } };
      venue_name?: unknown;
    };
    const sent = patches(calls);
    expect(sent).toHaveLength(2);
    const second = sent[1]?.body as Sent;
    expect(second.expected_revision).toBe(5);
    expect(second.texts.en.title).toBe('Mine');
    expect(second.venue_name).toBeNull(); // mine over theirs: the form wins
    expect(view.find('section[aria-label="Someone else saved this event first"]')).toBeNull();
    await view.unmount();
  });

  it('a second conflict opens the panel again', async () => {
    const { calls, view } = await conflict();
    await click(view.button('Save mine over theirs'));
    await flush();
    expect(patches(calls)).toHaveLength(2);
    expect(view.find('section[aria-label="Someone else saved this event first"]')).not.toBeNull();
    await view.unmount();
  });

  it('says the event is gone when the newer version cannot be loaded', async () => {
    let loads = 0;
    stubFetch({
      [`GET ${API}/e1`]: () =>
        loads++ === 0 ? eventDetail({ revision: 4 }) : refusal(404, 'not_found'),
      [`PATCH ${API}/e1`]: () => refusal(409, 'stale'),
    });
    const view = await mount(<EventEditor {...props} />);
    await flush();
    await setValue(field('text-en-title'), 'Mine');
    await act(async () => {
      document
        .querySelector('form')
        ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    await flush();
    expect(view.find('[role="alert"]')?.textContent).toBe('This event no longer exists.');
    expect(view.find('form')).toBeNull();
    await view.unmount();
  });
});
