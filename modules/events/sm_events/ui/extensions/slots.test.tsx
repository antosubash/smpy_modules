// @vitest-environment happy-dom
// biome-ignore-all lint/correctness/noComponentHookFactories: plugin loaders are test doubles
import type { ComponentType } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { DetailProps, EventChipProps } from '../calendar/types';
import { occurrence } from '../page-tests/calendar-support';
import { flush } from '../page-tests/support';
import { mount } from '../page-tests/test-dom';
import { resetReported } from './PluginBoundary';
import {
  clearExtensions,
  registerEventType,
  registerSource,
  registerToolbarItem,
} from './registry';
import { buildSlots } from './slots';

const Default: ComponentType<EventChipProps> = ({ occurrence: o }) => (
  <span data-testid="default">{o.title}</span>
);
const chipProps = (o = occurrence()): EventChipProps => ({
  occurrence: o,
  view: 'month',
  timeText: '09:00',
  Default,
});
const DefaultDetail: ComponentType<DetailProps> = ({ occurrence: o }) => (
  <div data-testid="default-detail">{o.title}</div>
);
const detailProps = (o = occurrence()): DetailProps => ({
  occurrence: o,
  gridTimeZone: 'UTC',
  close: () => {},
  actions: null,
  Default: DefaultDetail,
});

beforeEach(() => {
  clearExtensions();
  resetReported();
});
afterEach(() => {
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

const named = (label: string) => async () => ({
  default: () => <b data-testid="plugin">{label}</b>,
});

it('a chip dispatches on source, then type, else Default', async () => {
  registerSource({ id: 'acme:s', Chip: named('from source') });
  registerEventType({ id: 'acme:talk', Chip: named('from type') });
  const Chip = buildSlots('console').EventChip as ComponentType<EventChipProps>;
  const cases: [Parameters<typeof occurrence>[0], string][] = [
    [{ source: 'acme:s', type: 'acme:talk' }, 'from source'],
    [{ source: 'events', type: 'acme:talk' }, 'from type'],
    [{ source: 'events', type: 'event' }, 'Planning'],
    [{ source: 'gone:x', type: 'event' }, 'Planning'], // an unregistered source: the default
  ];
  for (const [fields, text] of cases) {
    const view = await mount(<Chip {...chipProps(occurrence(fields))} />);
    await flush();
    expect(view.host.textContent).toBe(text);
    await view.unmount();
  }
});

it('a crashing plugin chip renders Default and does not throw', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  registerSource({
    id: 'acme:s',
    Chip: async () => ({
      default: () => {
        throw new Error('boom');
      },
    }),
  });
  const Chip = buildSlots('console').EventChip as ComponentType<EventChipProps>;
  const view = await mount(<Chip {...chipProps(occurrence({ source: 'acme:s' }))} />);
  await flush();
  expect(view.find('[data-testid="default"]')).not.toBeNull();
  await view.unmount();
});

it('a failing lazy import falls back to Default too', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  registerEventType({ id: 'acme:talk', Chip: () => Promise.reject(new Error('chunk')) });
  const Chip = buildSlots('console').EventChip as ComponentType<EventChipProps>;
  const view = await mount(<Chip {...chipProps(occurrence({ type: 'acme:talk' }))} />);
  await flush();
  expect(view.find('[data-testid="default"]')).not.toBeNull();
  await view.unmount();
});

it('the public surface uses PublicDetail or Default, never Detail', async () => {
  registerSource({ id: 'acme:s', Detail: named('console detail') });
  registerEventType({ id: 'acme:talk', PublicDetail: named('public detail') });
  const publicDetail = buildSlots('public').Detail as ComponentType<DetailProps>;
  const consoleDetail = buildSlots('console').Detail as ComponentType<DetailProps>;

  let view = await mount(
    <PublicWrap Slot={publicDetail} props={detailProps(occurrence({ source: 'acme:s' }))} />,
  );
  await flush();
  expect(view.host.textContent).not.toContain('console detail'); // a source's Detail is console-only
  expect(view.find('[data-testid="default-detail"]')).not.toBeNull();
  await view.unmount();

  view = await mount(
    <PublicWrap Slot={publicDetail} props={detailProps(occurrence({ type: 'acme:talk' }))} />,
  );
  await flush();
  expect(view.host.textContent).toContain('public detail');
  expect(view.find('[data-testid="default-detail"]')).not.toBeNull();
  await view.unmount();

  view = await mount(
    <PublicWrap Slot={consoleDetail} props={detailProps(occurrence({ source: 'acme:s' }))} />,
  );
  await flush();
  expect(view.host.textContent).toContain('console detail');
  await view.unmount();
});

function PublicWrap({ Slot, props }: { Slot: ComponentType<DetailProps>; props: DetailProps }) {
  return <Slot {...props} />;
}

it('toolbar items render on their surface only, in id order', async () => {
  registerToolbarItem({ id: 'b', placement: 'end', surfaces: ['console'], Component: named('B') });
  registerToolbarItem({
    id: 'a',
    placement: 'end',
    surfaces: ['console', 'public'],
    Component: named('A'),
  });
  const state = {
    view: 'month',
    date: '2026-03-01',
    tzMode: 'calendar',
    calendars: [],
    categories: [],
    types: [],
    sources: [],
  } as never;
  const End = buildSlots('console').ToolbarEnd as ComponentType<{ state: never; range: null }>;
  const view = await mount(<End state={state} range={null} />);
  await flush();
  expect([...view.all('[data-testid="plugin"]')].map((e) => e.textContent)).toEqual(['A', 'B']);
  await view.unmount();
  const publicSlots = buildSlots('public');
  expect(publicSlots.ToolbarStart).toBeUndefined(); // none registered for the start
  const PublicEnd = publicSlots.ToolbarEnd as ComponentType<{ state: never; range: null }>;
  const publicView = await mount(<PublicEnd state={state} range={null} />);
  await flush();
  expect([...publicView.all('[data-testid="plugin"]')].map((e) => e.textContent)).toEqual(['A']);
  await publicView.unmount();
});

it('a script-like title is only ever text', async () => {
  const title = '<script>window.hacked = 1</script><img src=x onerror=alert(1)>';
  registerEventType({
    id: 'acme:talk',
    Chip: async () => ({ default: ({ occurrence: o }) => <i>{o.title}</i> }),
  });
  const Chip = buildSlots('console').EventChip as ComponentType<EventChipProps>;
  const view = await mount(<Chip {...chipProps(occurrence({ type: 'acme:talk', title }))} />);
  await flush();
  expect(view.host.querySelector('script, img')).toBeNull();
  expect(view.host.textContent).toBe(title);
  const plain = await mount(<Chip {...chipProps(occurrence({ title }))} />);
  expect(plain.host.querySelector('script, img')).toBeNull();
  await plain.unmount();
  await view.unmount();
});
