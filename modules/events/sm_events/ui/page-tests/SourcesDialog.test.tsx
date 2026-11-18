// @vitest-environment happy-dom
// biome-ignore-all lint/correctness/noComponentHookFactories: plugin loaders are test doubles

import { setCsrfToken } from '@simple-module-py/ui/lib/api';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { clearExtensions, registerSource } from '../extensions/registry';
import type { SourceSettingsProps } from '../extensions/types';
import { button, calendar, flush, stubFetch } from './support';
import { act, click, mount, setValue } from './test-dom';

vi.mock('@inertiajs/react', async () => (await import('./support')).inertiaMock());
const { default: Calendars } = await import('../../pages/Calendars');
const API = '/api/events/calendars';
const SOURCES = '/api/events/sources';
const props = { can_create: false, can_manage: false, user_id: 'u1', default_timezone: 'UTC' };

const SOURCE_LIST = [
  {
    id: 'acme:desk',
    label_key: 'acme.sources.desk',
    color: '#112233',
    icon: null,
    public: true,
    has_settings: true,
    settings_schema: { type: 'object' },
  },
  {
    id: 'acme:plain',
    label_key: 'acme.sources.plain',
    color: null,
    icon: null,
    public: false,
    has_settings: false,
    settings_schema: null,
  },
  {
    id: 'acme:json',
    label_key: 'acme.sources.json',
    color: null,
    icon: null,
    public: false,
    has_settings: true,
    settings_schema: { type: 'object' },
  },
];

let received: SourceSettingsProps | null = null;
function Section(p: SourceSettingsProps) {
  received = p;
  return (
    <div data-testid="desk-section">
      <input
        id="desk-field"
        value={String(p.settings.field ?? '')}
        onChange={(e) => p.onChange({ ...p.settings, field: e.target.value })}
      />
      <span data-testid="desk-error">{p.errors.field}</span>
    </div>
  );
}

const withSources = (sources: unknown[], extra = {}) =>
  calendar({ sources, sources_version: 'v1', ...extra });

beforeEach(() => {
  clearExtensions();
  received = null;
  registerSource({ id: 'acme:desk', SettingsSection: async () => ({ default: Section }) });
});
afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  document.body.innerHTML = '';
});

async function open(cal = withSources([]), routes: Record<string, unknown> = {}) {
  const calls = stubFetch({
    [`GET ${API}`]: [cal],
    [`GET ${SOURCES}`]: SOURCE_LIST,
    ...routes,
  });
  const view = await mount(<Calendars {...props} />);
  await flush();
  await click(document.querySelector('button[aria-label^="Sources"]') as HTMLElement);
  await flush();
  return { view, calls };
}

const dialog = () => document.querySelector('[role="dialog"]') as HTMLElement;
const toggle = (id: string) => document.getElementById(`source-${id}`) as HTMLInputElement;

it('lists the registered sources with a public badge and a fallback label', async () => {
  const { view } = await open();
  const text = dialog().textContent ?? '';
  expect(text).toContain('acme:desk'); // no catalogue: the id
  expect(text).toContain('acme:plain');
  expect(dialog().querySelectorAll('[data-testid="source-public"]')).toHaveLength(1);
  await view.unmount();
});

it("enabling shows the plugin's section, or a JSON fallback, or nothing", async () => {
  const { view } = await open();
  await click(toggle('acme:desk'));
  await flush();
  expect(dialog().querySelector('[data-testid="desk-section"]')).not.toBeNull();
  expect(received?.calendar.id).toBe('c1');
  expect(Object.keys(received ?? {}).sort()).toEqual([
    'calendar',
    'errors',
    'onChange',
    'settings',
  ]);
  await click(toggle('acme:json'));
  await flush();
  expect(dialog().querySelector('textarea')).not.toBeNull();
  await click(toggle('acme:plain'));
  await flush();
  expect(dialog().querySelectorAll('textarea')).toHaveLength(1); // no settings, no form
  await view.unmount();
});

it('saves with PUT, the entries and the version it read', async () => {
  const saved = withSources(
    [{ id: 'acme:desk', settings: { field: 'x' }, installed: true, label_key: null }],
    {
      sources_version: 'v2',
    },
  );
  const { view, calls } = await open(withSources([]), {
    [`PUT ${API}/c1/sources`]: () => saved,
  });
  await click(toggle('acme:desk'));
  await flush();
  await setValue(document.getElementById('desk-field') as HTMLInputElement, 'x');
  await click(button('Save', dialog()));
  await flush();
  const put = calls.find((c) => c.method === 'PUT');
  expect(put?.body).toEqual({
    sources: [{ id: 'acme:desk', settings: { field: 'x' } }],
    expected: 'v1',
  });
  await view.unmount();
});

it('a 422 on the settings lands on the section, by field', async () => {
  const { view } = await open(withSources([]), {
    [`PUT ${API}/c1/sources`]: () =>
      Response.json(
        {
          detail: [
            {
              loc: ['body', 'sources', 0, 'settings', 'field'],
              msg: 'That is not allowed',
              type: 'x',
            },
          ],
        },
        { status: 422 },
      ),
  });
  await click(toggle('acme:desk'));
  await flush();
  await click(button('Save', dialog()));
  await flush();
  expect(dialog().querySelector('[data-testid="desk-error"]')?.textContent).toBe(
    'That is not allowed',
  );
  await view.unmount();
});

it('keeps a source that is not installed on save, and removes it only after a confirmation', async () => {
  const stored = { id: 'gone:thing', settings: { a: 1 }, installed: false, label_key: null };
  const { view, calls } = await open(withSources([stored]), {
    [`PUT ${API}/c1/sources`]: () => withSources([]),
  });
  expect(dialog().textContent).toContain('gone:thing');
  expect(dialog().textContent).toMatch(/not installed/i);
  await click(button('Save', dialog()));
  await flush();
  expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({
    sources: [{ id: 'gone:thing', settings: { a: 1 } }],
    expected: 'v1',
  });
  await view.unmount();
});

it('removing a source that is not installed asks first', async () => {
  const stored = { id: 'gone:thing', settings: {}, installed: false, label_key: null };
  const { view, calls } = await open(withSources([stored]), {
    [`PUT ${API}/c1/sources`]: () => withSources([]),
  });
  await click(button('Remove', dialog()));
  const confirm = document.querySelector('[role="alertdialog"]') as HTMLElement;
  expect(confirm).not.toBeNull();
  await click(button('Remove', confirm));
  await flush();
  await click(button('Save', dialog()));
  await flush();
  expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ sources: [], expected: 'v1' });
  await view.unmount();
});

it('a stale write says so', async () => {
  const { view } = await open(withSources([]), {
    [`PUT ${API}/c1/sources`]: () => Response.json({ detail: 'x', code: 'stale' }, { status: 409 }),
  });
  await click(toggle('acme:plain'));
  await click(button('Save', dialog()));
  await flush();
  expect(dialog().textContent).toMatch(/changed by someone else/i);
  await view.unmount();
});

it('the Sources action is hidden without the right to change visibility', async () => {
  stubFetch({
    [`GET ${API}`]: [withSources([], { can_own: false })],
    [`GET ${SOURCES}`]: SOURCE_LIST,
  });
  const view = await mount(<Calendars {...props} />);
  await flush();
  expect(document.querySelector('button[aria-label^="Sources"]')).toBeNull();
  await view.unmount();
  void act;
});
