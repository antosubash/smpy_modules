// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, expect, it } from 'vitest';
import type { Filters, Report } from '../utils/types';
import { ReportFilters } from './ReportFilters';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
afterEach(async () => {
  await act(async () => root?.unmount());
  document.body.innerHTML = '';
});
const filters: Filters = {
  start: '2026-11-01',
  end: '2026-11-08',
  path: '',
  event: '',
  country: 'AT',
  region: 'AT-9',
  city: '2761369',
};
const report = {
  breakdowns: {
    country: [
      { value: 'AT', label: 'Austria', count: 3 },
      { value: '', label: 'Unknown', count: 1 },
    ],
    region: [],
    city: [],
  },
} as unknown as Report;
const button = (text: string) =>
  Array.from(document.querySelectorAll('button')).find(
    (item) => item.textContent === text,
  ) as HTMLButtonElement;
const select = (text: string) =>
  document.getElementById(
    Array.from(document.querySelectorAll('label')).find((item) => item.textContent === text)
      ?.htmlFor ?? '',
  ) as HTMLSelectElement;
async function mount(onChange: (next: Filters) => void) {
  const container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(async () =>
    root.render(<ReportFilters value={filters} onChange={onChange} report={report} />),
  );
  await act(async () => button('Filters').click());
}
it('edits a draft without querying, then applies unknown country and clears narrower filters', async () => {
  let updated: Filters | undefined;
  await mount((next) => {
    updated = next;
  });
  expect(Array.from(select('Country').options).map((option) => option.value)).toEqual([
    '',
    'AT',
    '__unknown__',
  ]);
  await act(async () => {
    select('Country').value = '__unknown__';
    select('Country').dispatchEvent(new Event('change', { bubbles: true }));
  });
  expect(updated).toBeUndefined();
  await act(async () => button('Apply').click());
  expect(updated).toEqual({ ...filters, country: '__unknown__', region: '', city: '' });
  expect(document.querySelector('[role="dialog"]')).toBeNull();
});
it('cancel discards edits and reopening starts from applied filters', async () => {
  let updated: Filters | undefined;
  await mount((next) => {
    updated = next;
  });
  await act(async () => {
    select('Country').value = '';
    select('Country').dispatchEvent(new Event('change', { bubbles: true }));
  });
  await act(async () => button('Cancel').click());
  expect(updated).toBeUndefined();
  await act(async () => button('Filters').click());
  expect(select('Country').value).toBe('AT');
});
