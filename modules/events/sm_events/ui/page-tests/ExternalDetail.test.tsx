// @vitest-environment happy-dom
import { afterEach, expect, it } from 'vitest';
import { DefaultDetail } from '../calendar/DetailPopover';
import ExternalDetail from '../components/subscriptions/ExternalDetail';
import { mount } from './test-dom';

afterEach(() => {
  document.body.innerHTML = '';
});

const external = {
  source: 'subscriptions',
  key: 'k',
  calendar_id: 'c',
  start: '2027-03-10T09:00:00Z',
  end: '2027-03-10T10:00:00Z',
  all_day: false,
  timezone: 'UTC',
  start_date: null,
  end_date: null,
  title: 'Holiday',
  lang: '',
  color: '#2563eb',
  url: 'https://source.example/event/1',
  status: 'confirmed',
  type: 'event',
  editable: false,
  event_id: null,
  original_start: null,
  event_status: null,
  origin_label: 'Public holidays',
} as const;

const props = (over: Record<string, unknown> = {}) => ({
  occurrence: { ...external, ...over },
  gridTimeZone: 'UTC',
  close: () => {},
  actions: null,
  Default: DefaultDetail,
});

it('shows the stored place as literal text', async () => {
  const view = await mount(<ExternalDetail {...props({ location: 'Room <b>4</b>' })} />);
  const place = document.querySelector('[data-testid="external-location"]');
  expect(place?.textContent).toBe('Room <b>4</b>');
  expect(place?.querySelector('b')).toBeNull();
  await view.unmount();
  const none = await mount(<ExternalDetail {...props({ location: null })} />);
  expect(document.querySelector('[data-testid="external-location"]')).toBeNull();
  await none.unmount();
});

it('renders title and text as literal text, never as markup', async () => {
  const view = await mount(
    <ExternalDetail {...props({ title: '<img src=x onerror=alert(1)>' })} />,
  );
  expect(view.host.textContent).toContain('<img src=x onerror=alert(1)>');
  expect(view.host.querySelector('img')).toBeNull();
  await view.unmount();
});

it('links to the source with target blank and rel noopener noreferrer nofollow', async () => {
  const view = await mount(<ExternalDetail {...props()} />);
  const link = view.find<HTMLAnchorElement>('a');
  expect(link?.getAttribute('href')).toBe('https://source.example/event/1');
  expect(link?.getAttribute('target')).toBe('_blank');
  expect(link?.getAttribute('rel')).toBe('noopener noreferrer nofollow');
  await view.unmount();
});

it('has no link when the url is null or not a web address', async () => {
  for (const url of [
    null,
    'javascript:alert(1)',
    'data:text/html,x',
    'ftp://x.example/',
    '/relative',
  ]) {
    const view = await mount(<ExternalDetail {...props({ url })} />);
    expect(view.find('a'), String(url)).toBeNull();
    await view.unmount();
  }
});

it('says where it comes from', async () => {
  const view = await mount(<ExternalDetail {...props()} />);
  expect(view.host.textContent).toContain('From Public holidays (external calendar)');
  await view.unmount();
});

it('offers no edit, move, remind or register control', async () => {
  const view = await mount(
    <ExternalDetail {...props()} actions={<button type="button">Edit</button>} />,
  );
  expect(view.all('button')).toHaveLength(0);
  expect(view.all('button, input, select, [role="button"], [draggable="true"]')).toHaveLength(0);
  await view.unmount();
});
