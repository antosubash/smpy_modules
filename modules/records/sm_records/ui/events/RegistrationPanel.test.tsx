// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  definition,
  field,
  fill,
  input,
  send,
  server,
} from '../components/public_submissions/form/record-form-test-support';
import { click, mount, settle, setValue } from '../page-tests/test-dom';

vi.mock('../components/public_submissions/form/CaptchaWidget', () => ({
  CaptchaWidget: () => null,
}));
const { default: RegistrationPanel } = await import('./RegistrationPanel');

const EID = '3f1c2a52-0000-4000-8000-000000000001';
const props = { typeKey: 'regs', eventId: EID, occurrenceKey: EID, locale: 'de' };
const info = {
  title: 'Open day',
  when_text: 'Wed 1 Jul, 10:00',
  venue_name: 'Hall',
  address: null,
};
const open = (over: Record<string, unknown> = {}) => ({
  availability: {
    state: 'open',
    seats_left: null,
    few_left: false,
    opens_at: null,
    closes_at: null,
  },
  event: info,
  definition: {
    ...definition({ kind: 'registration' as never, double_opt_in: true } as never),
    fields: [
      field('sm_name', 'text', { required: true }),
      field('sm_email', 'email', { required: true }),
    ],
    consent: null,
  },
  ...over,
});
const view = (state: string, extra: Record<string, unknown> = {}) => ({
  availability: {
    state,
    seats_left: null,
    few_left: false,
    opens_at: null,
    closes_at: null,
    ...extra,
  },
  event: info,
  definition: null,
});
const text = () => document.body.textContent ?? '';

beforeEach(() => {
  document.documentElement.lang = 'de';
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
  document.documentElement.lang = '';
});

async function fillIn(v: Awaited<ReturnType<typeof mount>>) {
  await setValue(input(v, 'sm_name') as HTMLInputElement, 'Ada');
  await setValue(input(v, 'sm_email') as HTMLInputElement, 'ada@example.org');
}

it('asks the provider route for the event and occurrence, and posts the token with no event field', async () => {
  const calls = server({ status: 200, body: open() }, { status: 202, body: { ok: true } });
  const v = await mount(<RegistrationPanel {...props} />);
  await settle();
  expect(calls[0]?.url).toBe(
    `/api/records/submissions/regs/registration?event=${EID}&occurrence=${EID}&locale=de`,
  );
  expect(text()).toContain('Open day');
  expect(text()).toContain('Wed 1 Jul, 10:00');
  await fillIn(v);
  await send(v);
  const body = JSON.parse(String(calls[1]?.init?.body));
  expect(calls[1]?.url).toBe('/api/records/submissions/regs/submit');
  expect(body.token).toBe('tok-1');
  expect(JSON.stringify(body)).not.toContain(EID);
  expect(Object.keys(body).filter((k) => /event|occurrence/.test(k))).toEqual([]);
  await v.unmount();
});

it('double opt-in says to check the inbox; single opt-in says it is registered; never "already"', async () => {
  server({ status: 200, body: open() }, { status: 202, body: { ok: true } });
  const a = await mount(<RegistrationPanel {...props} />);
  await settle();
  await fillIn(a);
  await send(a);
  expect(text()).toContain('Check your inbox');
  expect(text().toLowerCase()).not.toContain('already');
  await a.unmount();
  const single = open();
  single.definition.double_opt_in = false;
  server({ status: 200, body: single }, { status: 202, body: { ok: true } });
  const b = await mount(<RegistrationPanel {...props} />);
  await settle();
  await fillIn(b);
  await send(b);
  expect(text()).toContain('registration is in');
  expect(text().toLowerCase()).not.toContain('already');
  await b.unmount();
});

it('a 409 registration_full swaps to fully booked without a reload', async () => {
  const calls = server(
    { status: 200, body: open() },
    { status: 409, body: { code: 'registration_full', detail: 'x' } },
  );
  const v = await mount(<RegistrationPanel {...props} />);
  await settle();
  await fillIn(v);
  await send(v);
  expect(calls).toHaveLength(2);
  expect(text()).toContain('fully booked');
  expect(v.find('form')).toBeNull();
  await v.unmount();
});

it.each([
  ['registration_closed', 'closed'],
  ['event_unavailable', 'no longer available'],
])('%s shows its own text', async (code, words) => {
  server({ status: 200, body: open() }, { status: 409, body: { code, detail: 'x' } });
  const v = await mount(<RegistrationPanel {...props} />);
  await settle();
  await fillIn(v);
  await send(v);
  expect(text()).toContain(words);
  await v.unmount();
});

it('seats_busy says to try again and keeps the form', async () => {
  server({ status: 200, body: open() }, { status: 409, body: { code: 'seats_busy', detail: 'x' } });
  const v = await mount(<RegistrationPanel {...props} />);
  await settle();
  await fillIn(v);
  await send(v);
  expect(text()).toContain('try again');
  expect(v.find('form')).not.toBeNull();
  await v.unmount();
});

it('form_expired refetches the registration view once and sends again', async () => {
  const calls = server(
    { status: 200, body: open() },
    { status: 400, body: { code: 'form_expired', detail: 'x' } },
    { status: 200, body: open() },
    { status: 202, body: { ok: true } },
  );
  const v = await mount(<RegistrationPanel {...props} />);
  await settle();
  await fillIn(v);
  await send(v);
  await settle();
  expect(calls.map((c) => c.url.split('?')[0])).toEqual([
    '/api/records/submissions/regs/registration',
    '/api/records/submissions/regs/submit',
    '/api/records/submissions/regs/registration',
    '/api/records/submissions/regs/submit',
  ]);
  expect(text()).toContain('Check your inbox');
  await v.unmount();
});

it.each([
  ['full', {}, 'fully booked'],
  ['closed', {}, 'closed'],
  ['cancelled', {}, 'cancelled'],
])('the %s state shows its text and no form', async (state, extra, words) => {
  server({ status: 200, body: view(state, extra) });
  const v = await mount(<RegistrationPanel {...props} />);
  await settle();
  expect(text()).toContain(words);
  expect(v.find('form')).toBeNull();
  await v.unmount();
});

it('not-yet-open shows when registration opens', async () => {
  server({ status: 200, body: view('not_open_yet', { opens_at: '2026-06-01T07:00:00Z' }) });
  const v = await mount(<RegistrationPanel {...props} />);
  await settle();
  expect(text()).toContain('opens');
  expect(text()).toContain('2026');
  expect(v.find('form')).toBeNull();
  await v.unmount();
});

it('shows a state, or an exact number only when the server sent one', async () => {
  server({
    status: 200,
    body: open({
      availability: {
        state: 'open',
        seats_left: null,
        few_left: true,
        opens_at: null,
        closes_at: null,
      },
    }),
  });
  const a = await mount(<RegistrationPanel {...props} />);
  await settle();
  expect(text()).toContain('few seats left');
  await a.unmount();
  server({
    status: 200,
    body: open({
      availability: {
        state: 'open',
        seats_left: 7,
        few_left: false,
        opens_at: null,
        closes_at: null,
      },
    }),
  });
  const b = await mount(<RegistrationPanel {...props} />);
  await settle();
  expect(text()).toContain('7 seats left');
  await b.unmount();
  server({ status: 200, body: open() });
  const c = await mount(<RegistrationPanel {...props} />);
  await settle();
  expect(text()).not.toMatch(/seats? left/);
  await c.unmount();
});

it('a 404 renders nothing, and a network failure says so', async () => {
  server({ status: 404 });
  const a = await mount(<RegistrationPanel {...props} />);
  await settle();
  expect(a.host.innerHTML).toBe('');
  await a.unmount();
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Promise.reject(new TypeError('offline'))),
  );
  const b = await mount(<RegistrationPanel {...props} />);
  await settle();
  expect(b.host.querySelector('[role=alert]')).not.toBeNull();
  await b.unmount();
});

it('names no other registrant anywhere in the page', async () => {
  server({ status: 200, body: open() });
  const v = await mount(<RegistrationPanel {...props} />);
  await settle();
  expect(v.host.innerHTML).not.toMatch(/@|registrant|attendee/i);
  await click(null);
  await v.unmount();
});
