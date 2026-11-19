// @vitest-environment happy-dom
// biome-ignore-all lint/correctness/noComponentHookFactories: plugin loaders are test doubles

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { clearExtensions, registerEventType } from '../extensions/registry';
import type { EditorSectionProps } from '../extensions/types';
import { eventDetail, field, flush, stubFetch } from './support';
import { act, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { default: EventEditor } = await import('../../pages/EventEditor');
// biome-ignore lint/suspicious/noExplicitAny: the tests read request bodies loosely
type Body = Record<string, any>;
const API = '/api/events/events';
const TYPES = [
  { id: 'event', label_key: 'events.types.event' },
  { id: 'acme:talk', label_key: 'acme.types.talk' },
];
const base = {
  event_id: null as string | null,
  calendar: { id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' },
  content_locales: ['en'],
  categories: [],
  default_timezone: 'Europe/Vienna',
  types: TYPES,
};

let seen: EditorSectionProps | null = null;
function Section(props: EditorSectionProps) {
  seen = props;
  return (
    <div data-testid="talk-section">
      <input
        id="talk-speaker"
        disabled={props.readOnly}
        value={String(props.extra.speaker ?? '')}
        onChange={(e) => props.onChange({ ...props.extra, speaker: e.target.value })}
      />
      <span data-testid="talk-error">{props.errors.speaker}</span>
    </div>
  );
}

beforeEach(() => {
  clearExtensions();
  seen = null;
  history.replaceState(null, '', '/admin/events/edit/new?calendar=c1');
  registerEventType({ id: 'acme:talk', EditorSection: async () => ({ default: Section }) });
});
afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

const submit = async () => {
  await act(async () => {
    document
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
};
async function basics() {
  await setValue(field('text-en-title'), 'Talk');
  await setValue(field('event-start'), '2026-07-01T10:00');
  await setValue(field('event-end'), '2026-07-01T11:00');
}

it('shows the type picker on create only with two or more types', async () => {
  stubFetch({});
  const one = await mount(<EventEditor {...base} types={[TYPES[0] as (typeof TYPES)[0]]} />);
  expect(document.getElementById('event-type')).toBeNull();
  await one.unmount();
  const two = await mount(<EventEditor {...base} />);
  const select = document.getElementById('event-type') as HTMLSelectElement;
  expect(select).not.toBeNull();
  expect([...select.options].map((o) => o.value)).toEqual(['event', 'acme:talk']);
  expect(document.querySelector('[data-testid="talk-section"]')).toBeNull(); // the default has none
  await two.unmount();
});

it("creates with the chosen type and the section's extra", async () => {
  const calls = stubFetch({ [`POST ${API}`]: () => eventDetail({ id: 'n1', type: 'acme:talk' }) });
  const view = await mount(<EventEditor {...base} />);
  await basics();
  await setValue(document.getElementById('event-type') as HTMLSelectElement, 'acme:talk');
  await flush();
  expect(document.querySelector('[data-testid="talk-section"]')).not.toBeNull();
  expect(seen?.eventId).toBeNull();
  expect(seen?.readOnly).toBe(false);
  await setValue(document.getElementById('talk-speaker') as HTMLInputElement, 'Ada');
  await submit();
  const body = calls.find((c) => c.method === 'POST')?.body as Body;
  expect(body.type).toBe('acme:talk');
  expect(body.extra).toEqual({ speaker: 'Ada' });
  await view.unmount();
});

it('the type is read-only after create, and an unchanged extra is not sent', async () => {
  const detail = eventDetail({
    type: 'acme:talk',
    type_installed: true,
    extra: { speaker: 'Ada' },
  });
  const calls = stubFetch({
    [`GET ${API}/e1`]: detail,
    [`PATCH ${API}/e1`]: () => eventDetail({ revision: 5 }),
  });
  const view = await mount(<EventEditor {...base} event_id="e1" />);
  await flush();
  expect(document.getElementById('event-type')).toBeNull();
  expect(document.querySelector('[data-testid="event-type-readonly"]')?.textContent).toContain(
    'acme:talk',
  ); // no catalogue for the key: the id shows
  expect(seen?.extra).toEqual({ speaker: 'Ada' });
  expect(seen?.eventId).toBe('e1');
  await setValue(field('event-venue-name'), 'Hall');
  await submit();
  const patch = calls.find((c) => c.method === 'PATCH')?.body as Body;
  expect(patch.venue_name).toBe('Hall');
  expect('extra' in patch).toBe(false);
  await view.unmount();
});

it('sends extra on update when the section changed it', async () => {
  const calls = stubFetch({
    [`GET ${API}/e1`]: eventDetail({
      type: 'acme:talk',
      type_installed: true,
      extra: { speaker: 'Ada' },
    }),
    [`PATCH ${API}/e1`]: () => eventDetail({ revision: 5 }),
  });
  const view = await mount(<EventEditor {...base} event_id="e1" />);
  await flush();
  await setValue(document.getElementById('talk-speaker') as HTMLInputElement, 'Bo');
  await submit();
  const patch = calls.find((c) => c.method === 'PATCH')?.body as Body;
  expect(patch.extra).toEqual({ speaker: 'Bo' });
  await view.unmount();
});

it("a 422 on extra.speaker reaches the section with the server's message", async () => {
  stubFetch({
    [`POST ${API}`]: () =>
      Response.json(
        { detail: [{ loc: ['body', 'extra', 'speaker'], msg: 'Field required', type: 'missing' }] },
        { status: 422 },
      ),
  });
  const view = await mount(<EventEditor {...base} />);
  await basics();
  await setValue(document.getElementById('event-type') as HTMLSelectElement, 'acme:talk');
  await flush();
  await submit();
  expect(document.querySelector('[data-testid="talk-error"]')?.textContent).toBe('Field required');
  expect(seen?.errors).toEqual({ speaker: 'Field required' });
  await view.unmount();
});

it('a locked event gives the section readOnly', async () => {
  stubFetch({
    [`GET ${API}/e1`]: eventDetail({
      type: 'acme:talk',
      type_installed: true,
      extra: { speaker: 'Ada' },
      status: 'published',
      locked: true,
      can_publish: false,
    }),
  });
  const view = await mount(<EventEditor {...base} event_id="e1" />);
  await flush();
  expect(seen?.readOnly).toBe(true);
  expect((document.getElementById('talk-speaker') as HTMLInputElement).disabled).toBe(true);
  await view.unmount();
});

it('an uninstalled type shows a notice, no section, and never sends extra', async () => {
  const calls = stubFetch({
    [`GET ${API}/e1`]: eventDetail({
      type: 'gone:thing',
      type_installed: false,
      type_label_key: null,
      extra: { b: 1, a: [1, 2] },
    }),
    [`PATCH ${API}/e1`]: () => eventDetail({ revision: 5 }),
  });
  const view = await mount(<EventEditor {...base} event_id="e1" />);
  await flush();
  expect(document.querySelector('[data-testid="talk-section"]')).toBeNull();
  const notice = document.querySelector('[data-testid="type-not-installed"]');
  expect(notice?.getAttribute('role')).toBe('status');
  expect(notice?.textContent).toMatch(/not installed/i);
  await setValue(field('event-venue-name'), 'Hall');
  await submit();
  const patch = calls.find((c) => c.method === 'PATCH')?.body as Body;
  expect(patch.venue_name).toBe('Hall');
  expect('extra' in patch).toBe(false);
  await view.unmount();
});

it('sends no extra when the type has no section', async () => {
  const calls = stubFetch({ [`POST ${API}`]: () => eventDetail({ id: 'n1' }) });
  const view = await mount(<EventEditor {...base} />);
  await basics();
  await submit();
  const body = calls.find((c) => c.method === 'POST')?.body as Body;
  expect(body.type).toBe('event');
  expect(body.extra).toEqual({});
  await view.unmount();
});

it('a section that throws renders nothing and the form still saves', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  clearExtensions();
  registerEventType({
    id: 'acme:talk',
    EditorSection: async () => ({
      default: () => {
        throw new Error('boom');
      },
    }),
  });
  const calls = stubFetch({ [`POST ${API}`]: () => eventDetail({ id: 'n1' }) });
  const view = await mount(<EventEditor {...base} />);
  await basics();
  await setValue(document.getElementById('event-type') as HTMLSelectElement, 'acme:talk');
  await flush();
  await submit();
  expect(calls.some((c) => c.method === 'POST')).toBe(true);
  await view.unmount();
});
