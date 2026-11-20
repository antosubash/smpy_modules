// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { useState } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { clearExtensions, registerRegistration } from '../../extensions/registry';
import { flush, stubFetch } from '../../page-tests/support';
import { act, mount, setValue } from '../../page-tests/test-dom';
import { blankRegistration, type RegistrationForm } from '../../utils/registration-form';
import { RegistrationSection } from './RegistrationSection';

const ID = 'acme:forms';
const COUNTS = '/api/events/events/e1/registrations';

function Harness({
  start,
  eventId = 'e1',
  errors = {},
  seen = [],
  revision = 1,
}: {
  start?: Partial<RegistrationForm>;
  eventId?: string | null;
  errors?: Record<string, string>;
  seen?: RegistrationForm[];
  revision?: number;
}) {
  const [value, setValue_] = useState<RegistrationForm>({ ...blankRegistration(), ...start });
  seen[0] = value;
  return (
    <RegistrationSection
      value={value}
      onChange={(patch) => setValue_((v) => ({ ...v, ...patch }))}
      onEdit={() => {}}
      errors={errors}
      disabled={false}
      eventId={eventId}
      revision={revision}
      timezone="Europe/Vienna"
    />
  );
}

const section = () =>
  Promise.resolve({
    default: ({
      target,
      onChange,
      capacity,
    }: {
      target: string | null;
      onChange: (t: string | null) => void;
      capacity: number | null;
    }) => (
      <button
        type="button"
        data-testid="provider-section"
        data-capacity={String(capacity)}
        onClick={() => onChange('form_a')}
      >
        target={target ?? 'none'}
      </button>
    ),
  });

beforeEach(() => clearExtensions());
afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

const radio = (mode: string) =>
  document.querySelector<HTMLInputElement>(`input[type=radio][value=${mode}]`);

it('offers built-in registration only when a provider is registered', async () => {
  const none = await mount(<Harness eventId={null} />);
  expect(radio('none')).not.toBeNull();
  expect(radio('external')).not.toBeNull();
  expect(radio('builtin')).toBeNull();
  await none.unmount();
  registerRegistration({ id: ID, EditorSection: section });
  const some = await mount(<Harness eventId={null} />);
  expect(radio('builtin')).not.toBeNull();
  await some.unmount();
});

it('renders the provider section for built-in, inside a boundary, with the typed capacity', async () => {
  registerRegistration({ id: ID, EditorSection: section });
  stubFetch({ [`GET ${COUNTS}`]: { items: [], total: 0 } });
  const seen: RegistrationForm[] = [];
  const view = await mount(<Harness seen={seen} start={{ mode: 'builtin', provider: ID }} />);
  await flush();
  await setValue(document.getElementById('event-registration-capacity') as HTMLInputElement, '12');
  const part = document.querySelector<HTMLElement>('[data-testid=provider-section]');
  expect(part?.dataset.capacity).toBe('12');
  await act(async () => part?.click());
  expect(seen[0]?.target).toBe('form_a');
  await view.unmount();
});

it('takes the window as wall-clock inputs in the events timezone', async () => {
  registerRegistration({ id: ID });
  stubFetch({ [`GET ${COUNTS}`]: { items: [], total: 0 } });
  const seen: RegistrationForm[] = [];
  const view = await mount(<Harness seen={seen} start={{ mode: 'builtin', provider: ID }} />);
  const opens = document.getElementById('event-registration-opens') as HTMLInputElement;
  expect(opens.type).toBe('datetime-local');
  await setValue(opens, '2026-06-01T09:00');
  expect(seen[0]?.opens).toBe('2026-06-01T09:00');
  expect(document.body.textContent).toContain('Europe/Vienna');
  await view.unmount();
});

it('shows taken of capacity per date, and a date that no longer exists', async () => {
  registerRegistration({ id: ID });
  stubFetch({
    [`GET ${COUNTS}`]: {
      items: [
        {
          occurrence_key: 'a',
          start: 'x',
          start_local: '2026-07-01T10:00',
          taken: 3,
          capacity: 10,
        },
        { occurrence_key: 'b', start: null, start_local: null, taken: 1, capacity: 10 },
      ],
      total: 2,
    },
  });
  const view = await mount(<Harness start={{ mode: 'builtin', provider: ID }} />);
  await flush();
  const text = document.querySelector('[data-testid=registration-counts]')?.textContent ?? '';
  expect(text).toContain('1 Jul 2026');
  expect(text).toContain('3 of 10');
  expect(text).toContain('no longer exists');
  await view.unmount();
});

it('says so when the counts fail, and retries', async () => {
  registerRegistration({ id: ID });
  let calls = 0;
  stubFetch({
    [`GET ${COUNTS}`]: () => {
      calls += 1;
      return calls === 1
        ? Response.json({ detail: 'x', code: 'boom' }, { status: 500 })
        : { items: [], total: 0 };
    },
  });
  const view = await mount(<Harness start={{ mode: 'builtin', provider: ID }} />);
  await flush();
  expect(document.querySelector('[role=alert]')?.textContent).toContain('could not be loaded');
  await act(async () => view.button('Try again')?.click());
  await flush();
  expect(document.body.textContent).toContain('Nobody has registered yet');
  await view.unmount();
});

it('shows the server messages under the fields', async () => {
  registerRegistration({ id: ID });
  stubFetch({ [`GET ${COUNTS}`]: { items: [], total: 0 } });
  const view = await mount(
    <Harness
      start={{ mode: 'builtin', provider: ID }}
      errors={{ 'registration.capacity': 'Enter a whole number of seats, at least 1.' }}
    />,
  );
  expect(document.getElementById('event-registration-capacity-error')?.textContent).toContain(
    'whole number',
  );
  await view.unmount();
});

it('hides the form it may not read, and freezes a provider that is gone', async () => {
  const hidden = await mount(<Harness start={{ mode: 'builtin', provider: ID, hidden: true }} />);
  expect(document.body.textContent).toContain('hidden from you');
  expect(document.querySelector('input')).toBeNull();
  await hidden.unmount();
  stubFetch({ [`GET ${COUNTS}`]: { items: [], total: 0 } });
  const gone = await mount(<Harness start={{ mode: 'builtin', provider: ID, installed: false }} />);
  expect(document.body.textContent).toContain('not installed');
  expect(
    (document.getElementById('event-registration-capacity') as HTMLInputElement).disabled,
  ).toBe(true);
  await gone.unmount();
});

it('the external mode asks for the link only', async () => {
  const view = await mount(<Harness eventId={null} start={{ mode: 'external' }} />);
  expect(document.getElementById('event-registration-url')).not.toBeNull();
  expect(document.getElementById('event-registration-capacity')).toBeNull();
  await view.unmount();
});

it('loads the plugins itself on a cold visit: a loading line, then the provider', async () => {
  const { loadEventExtensions, resetLoader } = await import('../../extensions/load');
  resetLoader();
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  // A direct load of the editor: nothing registered, the glob's loaders still pending.
  void loadEventExtensions({
    'records/events-extensions.ts': async () => {
      await gate;
      registerRegistration({ id: ID, EditorSection: section });
    },
  });
  stubFetch({ [`GET ${COUNTS}`]: { items: [], total: 0 } });
  const view = await mount(<Harness eventId={null} />);
  expect(document.body.textContent).toContain('Loading registration options');
  expect(document.body.textContent).not.toContain('no registration form available');
  expect(radio('builtin')).toBeNull();
  release();
  await flush();
  expect(radio('builtin')).not.toBeNull();
  expect(document.body.textContent).not.toContain('Loading registration options');
  await view.unmount();
  resetLoader();
});

it('warns, with the numbers, when the capacity is lowered below seats already taken', async () => {
  registerRegistration({ id: ID });
  stubFetch({
    [`GET ${COUNTS}`]: {
      items: [
        {
          occurrence_key: 'a',
          start: 'x',
          start_local: '2026-07-01T10:00',
          taken: 8,
          capacity: 10,
        },
        {
          occurrence_key: 'b',
          start: 'y',
          start_local: '2026-07-08T10:00',
          taken: 3,
          capacity: 10,
        },
      ],
      total: 2,
    },
  });
  const view = await mount(<Harness start={{ mode: 'builtin', provider: ID, capacity: '10' }} />);
  await flush();
  expect(document.querySelector('[data-testid=capacity-warning]')).toBeNull();
  await setValue(document.getElementById('event-registration-capacity') as HTMLInputElement, '5');
  const warning = document.querySelector('[data-testid=capacity-warning]')?.textContent ?? '';
  expect(warning).toContain('8');
  expect(warning).toContain('5');
  expect(warning).toContain('nobody is removed');
  await view.unmount();
});

it('words the per-date counts as dates, not as raw timestamps', async () => {
  registerRegistration({ id: ID });
  stubFetch({
    [`GET ${COUNTS}`]: {
      items: [
        {
          occurrence_key: 'a',
          start: 'x',
          start_local: '2026-07-01T10:00',
          taken: 3,
          capacity: 10,
        },
      ],
      total: 1,
    },
  });
  const view = await mount(<Harness start={{ mode: 'builtin', provider: ID }} />);
  await flush();
  const counts = document.querySelector('[data-testid=registration-counts]')?.textContent ?? '';
  expect(counts).not.toContain('2026-07-01T10:00');
  expect(counts).toContain('Jul');
  await view.unmount();
});

it('refreshes the counts when the event is saved (its revision changes)', async () => {
  registerRegistration({ id: ID });
  let calls = 0;
  stubFetch({
    [`GET ${COUNTS}`]: () => {
      calls += 1;
      return { items: [], total: 0 };
    },
  });
  const view = await mount(<Harness start={{ mode: 'builtin', provider: ID }} revision={1} />);
  await flush();
  await view.render(<Harness start={{ mode: 'builtin', provider: ID }} revision={2} />);
  await flush();
  expect(calls).toBe(2);
  await view.unmount();
});
