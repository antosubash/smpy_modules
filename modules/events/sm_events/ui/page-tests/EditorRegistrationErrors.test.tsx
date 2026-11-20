// @vitest-environment happy-dom
// biome-ignore-all lint/correctness/noComponentHookFactories: plugin loaders are test doubles

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { clearExtensions, registerRegistration } from '../extensions/registry';
import { field, flush, stubFetch } from './support';
import { act, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { default: EventEditor } = await import('../../pages/EventEditor');
const props = {
  event_id: null as string | null,
  calendar: { id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' },
  content_locales: ['en', 'de'],
  categories: [],
  default_timezone: 'Europe/Vienna',
};

beforeEach(() => {
  history.replaceState(null, '', '/admin/events/edit/new?calendar=c1');
  clearExtensions();
  registerRegistration({ id: 'acme:forms' });
});
afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
  clearExtensions();
});

it('a closing time before the opening time is said so next to the closing time, not generically', async () => {
  stubFetch({
    'POST /api/events/events': () =>
      Response.json(
        {
          detail: 'Registration must close after it opens',
          code: 'registration_closes_before_opens',
          field: 'registration.closes_at_local',
        },
        { status: 422 },
      ),
  });
  const view = await mount(<EventEditor {...props} />);
  await setValue(field('text-en-title'), 'Concert');
  await act(async () => {
    document.querySelector<HTMLInputElement>('input[type=radio][value=builtin]')?.click();
  });
  await flush();
  await act(async () => {
    document
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
  const message = document.getElementById('event-registration-closes-error')?.textContent ?? '';
  expect(message).toContain('close after it opens');
  expect(document.body.textContent).not.toContain('registration settings are not valid');
  await view.unmount();
});
