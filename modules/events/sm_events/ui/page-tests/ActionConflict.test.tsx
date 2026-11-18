// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { type Call, eventDetail, field, flush, refusal, stubFetch } from './support';
import { click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { default: EventEditor } = await import('../../pages/EventEditor');
const API = '/api/events/events';
const PANEL = 'section[aria-label="Someone else saved this event first"]';
const props = {
  event_id: 'e1',
  calendar: { id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' },
  content_locales: ['en', 'de'],
  categories: [],
  default_timezone: 'Europe/Vienna',
};
const draft = () => eventDetail({ revision: 4, status: 'draft' });
const theirs = () => eventDetail({ revision: 5, status: 'draft', venue_name: 'Their hall' });
const patches = (calls: Call[]) => calls.filter((c) => c.method === 'PATCH');

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

/** Click Submit, type a title while it is in flight, then answer 409 stale. */
async function staleAction(typed: boolean) {
  let release: (value: unknown) => void = () => {};
  let loads = 0;
  const calls = stubFetch({
    [`GET ${API}/e1`]: () => (loads++ === 0 ? draft() : theirs()),
    [`POST ${API}/e1/submit`]: () =>
      new Promise((resolve) => {
        release = resolve;
      }),
    [`PATCH ${API}/e1`]: () => eventDetail({ revision: 6, status: 'draft' }),
  });
  const view = await mount(<EventEditor {...props} />);
  await flush();
  await click(view.button('Submit for review'));
  if (typed) await setValue(field('text-en-title'), 'Mine');
  release(refusal(409, 'stale'));
  await flush();
  return { calls, view };
}

const saveButton = (view: Awaited<ReturnType<typeof staleAction>>['view']) =>
  view.all('form button').find((b) => b.textContent === 'Save');

describe('a refused action with edits typed meanwhile', () => {
  it('opens the conflict panel, blocks Save and says the action was not applied', async () => {
    const { calls, view } = await staleAction(true);
    expect(view.find(PANEL)).not.toBeNull();
    expect(view.host.textContent).toContain('Your action was not applied.');
    expect(view.host.textContent).not.toContain('went through');
    expect(saveButton(view)?.hasAttribute('disabled')).toBe(true);
    expect(field('text-en-title').value).toBe('Mine');
    // Only what the user did not touch moved to their version.
    expect(field('event-venue-name').value).toBe('Their hall');
    expect(patches(calls)).toHaveLength(0);
    await view.unmount();
  });

  it('Save mine sends only the typed fields on top of their revision', async () => {
    const { calls, view } = await staleAction(true);
    await click(view.button('Save mine over theirs'));
    await flush();
    const sent = patches(calls);
    expect(sent).toHaveLength(1);
    const body = sent[0]?.body as {
      expected_revision: number;
      texts: { en: { title: string } };
      venue_name?: unknown;
    };
    expect(body.expected_revision).toBe(5);
    expect(body.texts.en.title).toBe('Mine');
    expect('venue_name' in body).toBe(false);
    expect(view.find(PANEL)).toBeNull();
    await view.unmount();
  });

  it('Load their version drops the typed edit and sends nothing', async () => {
    const { calls, view } = await staleAction(true);
    await click(view.button('Load their version'));
    expect(field('text-en-title').value).toBe('Concert');
    expect(field('event-venue-name').value).toBe('Their hall');
    expect(view.find(PANEL)).toBeNull();
    expect(patches(calls)).toHaveLength(0);
    await view.unmount();
  });
});

describe('a refused action with a clean form', () => {
  it('loads their version and says so, with no conflict panel', async () => {
    const { view } = await staleAction(false);
    expect(view.find(PANEL)).toBeNull();
    expect(field('event-venue-name').value).toBe('Their hall');
    expect(view.host.textContent).toContain('Their version is loaded now');
    await view.unmount();
  });
});
