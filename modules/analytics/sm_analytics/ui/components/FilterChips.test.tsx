// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, expect, it } from 'vitest';
import type { Filters, Report } from '../utils/types';
import { FilterChips } from './FilterChips';

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
  path: '/guide',
  event: 'download',
  country: 'AT',
  region: 'AT-9',
  city: '__unknown__',
};
const report = {
  breakdowns: {
    country: [{ value: 'AT', label: 'Austria', count: 1 }],
    region: [{ value: 'AT-9', label: 'Vienna', count: 1 }],
    city: [],
  },
} as unknown as Report;
async function mount(onChange: (next: Filters) => void, value = filters) {
  const container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(async () =>
    root.render(<FilterChips value={value} report={report} onChange={onChange} />),
  );
}
it('shows readable geo labels and Unknown while country removal clears descendants', async () => {
  let updated: Filters | undefined;
  await mount((next) => {
    updated = next;
  });
  expect(document.body.textContent).toContain('Country: Austria');
  expect(document.body.textContent).toContain('Region: Vienna');
  expect(document.body.textContent).toContain('City: Unknown');
  await act(async () =>
    document.querySelector<HTMLButtonElement>('[aria-label="Remove Country filter"]')?.click(),
  );
  expect(updated).toEqual({ ...filters, country: '', region: '', city: '' });
});
it('region removal preserves country and reset preserves dates', async () => {
  let updated: Filters | undefined;
  await mount((next) => {
    updated = next;
  });
  await act(async () =>
    document.querySelector<HTMLButtonElement>('[aria-label="Remove Region filter"]')?.click(),
  );
  expect(updated).toEqual({ ...filters, region: '', city: '' });
  await act(async () =>
    Array.from(document.querySelectorAll('button'))
      .find((item) => item.textContent === 'Clear filters')
      ?.click(),
  );
  expect(updated).toEqual({ ...filters, path: '', event: '', country: '', region: '', city: '' });
});

it('the unknown sentinel applies to geography only, not an event named __unknown__', async () => {
  await mount(() => {}, { ...filters, event: '__unknown__' });
  expect(document.body.textContent).toContain('Event name: __unknown__');
});
