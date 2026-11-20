// @vitest-environment happy-dom

import { afterEach, beforeEach, expect, it } from 'vitest';
import { clearExtensions, registerRegistration } from '../extensions/registry';
import { flush } from '../page-tests/support';
import { mount } from '../page-tests/test-dom';
import { RegistrationSlot } from './RegistrationSlot';
import type { PublicRegistration } from './types';

const EID = '3f1c2a52-0000-4000-8000-000000000001';
const reg = (over: Partial<PublicRegistration> = {}): PublicRegistration => ({
  mode: 'builtin',
  url: null,
  provider: 'acme:forms',
  target: 'form_a',
  occurrence_key: EID,
  upcoming: [],
  ...over,
});
const panel = () =>
  Promise.resolve({
    default: (p: { typeKey: string; eventId: string; occurrenceKey: string; locale: string }) => (
      <p data-testid="panel">{JSON.stringify(p)}</p>
    ),
  });

beforeEach(() => clearExtensions());
afterEach(() => {
  document.body.innerHTML = '';
});

it('external shows the registration button', async () => {
  const view = await mount(
    <RegistrationSlot
      registration={reg({ mode: 'external', url: 'https://r.example/x' })}
      locale="en"
    />,
  );
  const link = view.find<HTMLAnchorElement>('a');
  expect(link?.getAttribute('href')).toBe('https://r.example/x');
  expect(link?.textContent).toBe('Register');
  expect(link?.getAttribute('rel')).toContain('nofollow');
});

it('built-in renders the registered panel lazily with exactly the documented props', async () => {
  registerRegistration({ id: 'acme:forms', PublicPanel: panel });
  const view = await mount(<RegistrationSlot registration={reg()} locale="de" />);
  await flush();
  const props = JSON.parse(view.find('[data-testid=panel]')?.textContent ?? '{}');
  expect(props).toEqual({ typeKey: 'form_a', eventId: EID, occurrenceKey: EID, locale: 'de' });
});

it('a series occurrence keeps its whole key and names the event by its id', async () => {
  registerRegistration({ id: 'acme:forms', PublicPanel: panel });
  const key = `${EID}:20260706T080000Z`;
  const view = await mount(
    <RegistrationSlot registration={reg({ occurrence_key: key })} locale="en" />,
  );
  await flush();
  const props = JSON.parse(view.find('[data-testid=panel]')?.textContent ?? '{}');
  expect([props.eventId, props.occurrenceKey]).toEqual([EID, key]);
});

it('built-in with no panel registered renders nothing', async () => {
  const view = await mount(<RegistrationSlot registration={reg()} locale="en" />);
  await flush();
  expect(view.host.innerHTML).toBe('');
  registerRegistration({ id: 'acme:other', PublicPanel: panel }); // another provider's panel
  await view.render(<RegistrationSlot registration={reg()} locale="en" />);
  expect(view.host.innerHTML).toBe('');
});

it('a series page without a date lists the dates to choose from instead of a panel', async () => {
  registerRegistration({ id: 'acme:forms', PublicPanel: panel });
  const upcoming = [
    {
      date_param: '2026-07-06',
      url: '/events/x?date=2026-07-06',
      start_local: '2026-07-06T10:00',
      end_local: '2026-07-06T11:00',
      status: 'scheduled' as const,
    },
  ];
  const view = await mount(
    <RegistrationSlot registration={reg({ occurrence_key: null, upcoming })} locale="en" />,
  );
  await flush();
  expect(view.find('[data-testid=panel]')).toBeNull();
  expect(view.find('a')?.getAttribute('href')).toBe('/events/x?date=2026-07-06');
  expect(view.host.textContent).toContain('Choose a date to register');
});

it('none and an external mode without a link render nothing', async () => {
  const none = await mount(<RegistrationSlot registration={reg({ mode: 'none' })} locale="en" />);
  expect(none.host.innerHTML).toBe('');
  const noLink = await mount(
    <RegistrationSlot registration={reg({ mode: 'external', url: null })} locale="en" />,
  );
  expect(noLink.host.innerHTML).toBe('');
});
