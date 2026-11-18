// @vitest-environment happy-dom
import { useState } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, click, mount, setValue } from '../page-tests/test-dom';
import type { TypeRead } from '../utils/types';

vi.mock('../utils/api', async (original) => ({
  ...(await original<typeof import('../utils/api')>()),
  listTypes: vi.fn(),
}));
const { listTypes } = await import('../utils/api');
const { default: RecordDatesSettings } = await import('./RecordDatesSettings');
const { default: RecordDateDetail } = await import('./RecordDateDetail');

const def = (key: string, type: string, indexed = true) => ({
  key,
  type,
  label: key.toUpperCase(),
  required: false,
  unique: false,
  indexed,
  default: null,
  help: null,
  constraints: {},
  options: {},
});
const type = (key: string, fields: ReturnType<typeof def>[]) =>
  ({ key, label: key.toUpperCase(), label_plural: key, fields }) as unknown as TypeRead;
const TYPES = [
  type('deadlines', [
    def('title', 'text'),
    def('due', 'date'),
    def('until', 'date'),
    def('at', 'datetime'),
    def('ends', 'datetime'),
    def('hidden_date', 'date', false),
  ]),
  type('nodates', [def('name', 'text')]),
  type('meetings', [def('starts', 'datetime')]),
];
const calendar = { id: 'c1', name: 'Team', default_timezone: 'Europe/Vienna' };

beforeEach(() => {
  vi.mocked(listTypes).mockResolvedValue({ items: TYPES });
});
afterEach(() => {
  document.body.innerHTML = '';
  vi.clearAllMocks();
});

type Settings = Record<string, unknown>;
/** The settings as the dialog holds them: every change is fed back in. */
function Host({
  initial,
  errors,
  codes = {},
  onChange,
}: {
  initial: Settings;
  errors: Record<string, string>;
  codes?: Record<string, string>;
  onChange: (next: Settings) => void;
}) {
  const [settings, setSettings] = useState(initial);
  return (
    <RecordDatesSettings
      settings={settings}
      errors={errors}
      codes={codes}
      calendar={calendar}
      onChange={(next) => {
        setSettings(next);
        onChange(next);
      }}
    />
  );
}
async function open(
  settings: Settings = {},
  errors: Record<string, string> = {},
  codes: Record<string, string> = {},
) {
  const onChange = vi.fn<(next: Settings) => void>();
  const view = await mount(
    <Host initial={settings} errors={errors} codes={codes} onChange={onChange} />,
  );
  await act(async () => new Promise((r) => setTimeout(r, 10)));
  return { view, onChange };
}
const options = (id: string) =>
  [...(document.getElementById(id) as HTMLSelectElement).options]
    .map((o) => o.value)
    .filter(Boolean);

const one = { mappings: [{ type_key: 'deadlines', field: 'due' }] };

it('lists only types with, and fields that are, indexed date or datetime fields', async () => {
  const { view } = await open(one);
  expect(options('records-dates-0-type')).toEqual(['deadlines', 'meetings']); // nodates has none
  expect(options('records-dates-0-field')).toEqual(['due', 'until', 'at', 'ends']);
  await view.unmount();
});

it('starts with one empty mapping, and picking a type resets the field', async () => {
  const { view, onChange } = await open({});
  expect(document.querySelectorAll('[data-testid="records-mapping"]')).toHaveLength(1);
  await setValue(document.getElementById('records-dates-0-type') as HTMLSelectElement, 'deadlines');
  expect(onChange).toHaveBeenLastCalledWith({
    mappings: [{ type_key: 'deadlines', field: '', end_field: null }],
  });
  await view.unmount();
});

it('adds up to five mappings and removes one', async () => {
  const { view, onChange } = await open(one);
  for (let i = 1; i < 5; i++) {
    const add = [...document.querySelectorAll('button')].find(
      (b) => b.textContent === 'Add a mapping',
    );
    expect(add?.hasAttribute('disabled')).toBe(false);
    await click(add);
  }
  const last = onChange.mock.calls.at(-1)?.[0] as { mappings: unknown[] };
  expect(last.mappings).toHaveLength(5);
  await view.unmount();
  const full = await open({ mappings: Array.from({ length: 5 }, () => one.mappings[0]) });
  const add = [...document.querySelectorAll('button')].find(
    (b) => b.textContent === 'Add a mapping',
  );
  expect(add?.hasAttribute('disabled')).toBe(true);
  await click(
    [...document.querySelectorAll('button')]
      .find((b) => b.textContent === 'Remove')
      ?.closest('button'),
  );
  const after = full.onChange.mock.calls.at(-1);
  expect((after ?? [])[0]).toMatchObject({ mappings: [{}, {}, {}, {}] });
  await full.view.unmount();
});

it('the end field excludes the start field and fields of the other kind', async () => {
  const { view } = await open(one);
  expect(options('records-dates-0-end')).toEqual(['until']); // another date field, not `due`, not a datetime
  await view.unmount();
  const timed = await open({ mappings: [{ type_key: 'deadlines', field: 'at' }] });
  expect(options('records-dates-0-end')).toEqual(['ends']);
  await timed.view.unmount();
});

it("shows the server's errors under mappings.<i>.<name> next to their input", async () => {
  const { view } = await open(one, {
    'mappings.0.field': 'Choose an indexed date or date-time field of this type',
    'mappings.0.type_key': 'No such type',
  });
  const text = document.body.textContent ?? '';
  expect(text).toContain('Choose an indexed date or date-time field of this type');
  expect(text).toContain('No such type');
  expect(document.getElementById('records-dates-0-field')?.getAttribute('aria-invalid')).toBe(
    'true',
  );
  await view.unmount();
});

it('shows a mapping the reader cannot view as a sentence, with nothing to edit or remove', async () => {
  const { view, onChange } = await open({
    mappings: [
      { type_key: 'deadlines', field: 'due' },
      { hidden: true, token: 'h1' },
    ],
  });
  const hidden = document.querySelector('[data-testid="records-mapping-hidden"]');
  expect(hidden?.textContent).toContain('A mapping you cannot view');
  expect(hidden?.querySelector('select, input, button')).toBeNull();
  expect(document.body.textContent).not.toContain('h1');
  expect(onChange).not.toHaveBeenCalled();
  await view.unmount();
});

it('keeps a field the type no longer offers visible and fixable, with a translated reason', async () => {
  const { view, onChange } = await open(
    { mappings: [{ type_key: 'nodates', field: 'due' }] },
    { 'mappings.0.field': 'English fallback' },
    { 'mappings.0.field': 'field_not_date' },
  );
  const type = document.getElementById('records-dates-0-type') as HTMLSelectElement;
  expect(type.value).toBe('nodates'); // the stored type stays selected though it has no dates
  const field = document.getElementById('records-dates-0-field') as HTMLSelectElement;
  expect(field.value).toBe('due');
  expect(field.selectedOptions[0]?.textContent).toBe('due (no longer available)');
  expect(document.body.textContent).toContain('no longer an indexed date');
  expect(document.body.textContent).not.toContain('English fallback');
  await setValue(type, 'deadlines');
  expect(onChange).toHaveBeenLastCalledWith({
    mappings: [{ type_key: 'deadlines', field: '', end_field: null }],
  });
  await view.unmount();
});

it('says so when the types cannot be loaded, and keeps the settings', async () => {
  vi.mocked(listTypes).mockImplementation(() => Promise.reject(new Error('offline')));
  const { view } = await open(one);
  expect(document.querySelector('[role="alert"]')).not.toBeNull();
  await view.unmount();
});

const Default = ({ actions }: { actions: React.ReactNode }) => (
  <div data-testid="default">{actions}</div>
);
const occ = (url: string | null) => ({ title: 'Tax', url }) as never;

it('the detail shows Open record when the record has a link', async () => {
  const view = await mount(
    <RecordDateDetail
      occurrence={occ('/admin/records/deadlines/u1')}
      gridTimeZone="UTC"
      close={() => {}}
      actions={null}
      Default={Default as never}
    />,
  );
  const link = document.querySelector('[data-testid="default"] a');
  expect(link?.textContent).toBe('Open record');
  expect(link?.getAttribute('href')).toBe('/admin/records/deadlines/u1');
  await view.unmount();
  const none = await mount(
    <RecordDateDetail
      occurrence={occ(null)}
      gridTimeZone="UTC"
      close={() => {}}
      actions={null}
      Default={Default as never}
    />,
  );
  expect(document.querySelector('[data-testid="default"] a')).toBeNull();
  await none.unmount();
});
