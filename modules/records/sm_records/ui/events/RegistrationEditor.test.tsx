// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, click, mount, settle } from '../page-tests/test-dom';
import type { RegistrationFormList } from '../utils/registration-forms-api';

vi.mock('../utils/registration-forms-api', () => ({
  listRegistrationForms: vi.fn(),
  createRegistrationForm: vi.fn(),
}));
const api = await import('../utils/registration-forms-api');
const { default: RegistrationEditor } = await import('./RegistrationEditor');

const form = (key: string, over = {}) => ({
  key,
  label: key.toUpperCase(),
  enabled: true,
  double_opt_in: true,
  attendees_url: `/admin/records/${key}`,
  ...over,
});
const answer = (over: Partial<RegistrationFormList> = {}): RegistrationFormList => ({
  items: [form('a'), form('b')],
  can_create: true,
  ...over,
});
const props = (over = {}) => ({
  target: null as string | null,
  onChange: vi.fn(),
  eventId: 'e1',
  capacity: null as number | null,
  readOnly: false,
  errors: {},
  ...over,
});

beforeEach(() => vi.mocked(api.listRegistrationForms).mockResolvedValue(answer()));
afterEach(() => {
  document.body.innerHTML = '';
  vi.clearAllMocks();
});

const select = () => document.getElementById('records-registration-form') as HTMLSelectElement;
const text = () => document.body.textContent ?? '';

it('lists the forms and choosing one reports its key', async () => {
  const p = props();
  const view = await mount(<RegistrationEditor {...p} />);
  await settle();
  expect([...select().options].map((o) => o.value)).toEqual(['', 'a', 'b']);
  await act(async () => {
    select().value = 'b';
    select().dispatchEvent(new Event('change', { bubbles: true }));
  });
  expect(p.onChange).toHaveBeenCalledWith('b');
  await view.unmount();
});

it('offers to create a form only when the list says the caller may, and selects the new one', async () => {
  vi.mocked(api.listRegistrationForms).mockResolvedValue(answer({ can_create: false }));
  const none = await mount(<RegistrationEditor {...props()} />);
  await settle();
  expect(text()).not.toContain('Create a registration form');
  await none.unmount();

  vi.mocked(api.listRegistrationForms).mockResolvedValue(answer());
  vi.mocked(api.createRegistrationForm).mockResolvedValue({ key: 'c' });
  const p = props();
  const view = await mount(<RegistrationEditor {...p} />);
  await settle();
  await click(view.button('Create a registration form'));
  await settle();
  expect(api.createRegistrationForm).toHaveBeenCalledTimes(1);
  expect(p.onChange).toHaveBeenCalledWith('c');
  await view.unmount();
});

it('shows the attendee link only for a chosen form that has one', async () => {
  vi.mocked(api.listRegistrationForms).mockResolvedValue(
    answer({ items: [form('a'), form('b', { attendees_url: '' })] }),
  );
  const a = await mount(<RegistrationEditor {...props({ target: 'a' })} />);
  await settle();
  expect(document.querySelector('a')?.getAttribute('href')).toBe('/admin/records/a');
  await a.unmount();
  const b = await mount(<RegistrationEditor {...props({ target: 'b' })} />);
  await settle();
  expect(document.querySelector('a')).toBeNull();
  await b.unmount();
});

it('warns about a form without double opt-in only for a capacity-limited event', async () => {
  vi.mocked(api.listRegistrationForms).mockResolvedValue(
    answer({ items: [form('a', { double_opt_in: false }), form('b')] }),
  );
  const open = await mount(<RegistrationEditor {...props({ target: 'a', capacity: null })} />);
  await settle();
  expect(text()).not.toContain('no confirmation step');
  await open.unmount();
  const limited = await mount(<RegistrationEditor {...props({ target: 'a', capacity: 20 })} />);
  await settle();
  expect(document.querySelector('[role=alert]')?.textContent).toContain('no confirmation step');
  await limited.unmount();
  const safe = await mount(<RegistrationEditor {...props({ target: 'b', capacity: 20 })} />);
  await settle();
  expect(document.querySelector('[role=alert]')).toBeNull();
  await safe.unmount();
});

it('says a form is switched off, keeps an unlisted target visible, and shows the server message', async () => {
  vi.mocked(api.listRegistrationForms).mockResolvedValue(
    answer({ items: [form('a', { enabled: false })] }),
  );
  const view = await mount(
    <RegistrationEditor
      {...props({ target: 'a', errors: { target: 'That registration form does not exist.' } })}
    />,
  );
  await settle();
  expect(text()).toContain('switched off');
  expect(text()).toContain('does not exist');
  await view.unmount();
  const gone = await mount(<RegistrationEditor {...props({ target: 'old' })} />);
  await settle();
  expect([...select().options].map((o) => o.value)).toContain('old');
  await gone.unmount();
});

it('has no create button when read-only, and a failed load can be retried', async () => {
  const ro = await mount(<RegistrationEditor {...props({ readOnly: true })} />);
  await settle();
  expect(select().disabled).toBe(true);
  expect(text()).not.toContain('Create a registration form');
  await ro.unmount();
  vi.mocked(api.listRegistrationForms).mockRejectedValueOnce(new Error('x'));
  const view = await mount(<RegistrationEditor {...props()} />);
  await settle();
  expect(document.querySelector('[role=alert]')?.textContent).toContain('could not be loaded');
  await click(view.button('Try again'));
  await settle();
  expect(select()).not.toBeNull();
  await view.unmount();
});
