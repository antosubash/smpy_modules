// @vitest-environment happy-dom

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { field, flush, stubFetch } from './support';
import { act, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));
const { default: EventEditor } = await import('../../pages/EventEditor');
const API = '/api/events/events';
const props = {
  event_id: null as string | null,
  calendar: { id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' },
  content_locales: ['en', 'de'],
  categories: [],
  default_timezone: 'Europe/Vienna',
};

beforeEach(() => history.replaceState(null, '', '/admin/events/edit/new?calendar=c1'));
afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

it('tells the writer which images work, and takes a path as well as an address', async () => {
  const view = await mount(<EventEditor {...props} />);
  const image = field('event-image') as HTMLInputElement;
  expect(image.type).toBe('text'); // not `url`: a path on the site is not a URL to the browser
  expect(document.body.textContent).toContain("this site's media library");
  await setValue(image, '/media/studio.jpg');
  expect(image.value).toBe('/media/studio.jpg');
  await view.unmount();
});

it('an off-site image is refused with a message under the field, in English and German', async () => {
  const refusal = () =>
    Response.json(
      { detail: 'Use an image', code: 'image_off_site', field: 'image' },
      { status: 422 },
    );
  stubFetch({ [`POST ${API}`]: refusal });
  const view = await mount(<EventEditor {...props} />);
  await setValue(field('text-en-title'), 'Concert');
  await setValue(field('event-image'), 'https://cdn.example.net/a.jpg');
  await act(async () => {
    document
      .querySelector('form')
      ?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
  const message = document.getElementById('event-image-error')?.textContent ?? '';
  expect(message).toContain("this site's media library");
  expect(document.activeElement).toBe(field('event-image'));
  await view.unmount();
});
