// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import type { Filters } from '../utils/types';
import { DateRangeControl } from './DateRangeControl';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
afterEach(async () => {
  await act(async () => root?.unmount());
  document.body.innerHTML = '';
  vi.useRealTimers();
});
const filters: Filters = {
  start: '2026-11-01',
  end: '2026-11-08',
  path: '/guide',
  event: '',
  country: '',
  region: '',
  city: '',
};
const button = (name: string) =>
  Array.from(document.querySelectorAll('button')).find(
    (item) => item.textContent === name,
  ) as HTMLButtonElement;
async function mount(onChange: (next: Filters) => void) {
  const container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(<DateRangeControl value={filters} onChange={onChange} />));
  await act(async () =>
    document.querySelector<HTMLButtonElement>('[aria-label="Date range"]')?.click(),
  );
}
it.each([
  ['Today', '2026-11-08'],
  ['Last 7 days', '2026-11-02'],
  ['Last 30 days', '2026-10-10'],
  ['Last 90 days', '2026-08-11'],
])('uses inclusive UTC dates for %s', async (name, start) => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-11-08T00:30:00Z'));
  let updated: Filters | undefined;
  await mount((next) => {
    updated = next;
  });
  await act(async () => button(name).click());
  expect(updated).toEqual({ ...filters, start, end: '2026-11-08' });
});
it('custom dates stay drafts until Apply and enforce inclusive 366-day bounds', async () => {
  let updated: Filters | undefined;
  await mount((next) => {
    updated = next;
  });
  const inputs = Array.from(document.querySelectorAll<HTMLInputElement>('input[type="date"]'));
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    setter?.call(inputs[0], '2025-11-07');
    inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
  });
  expect(updated).toBeUndefined();
  expect(button('Apply').disabled).toBe(true);
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(
      inputs[0],
      '2025-11-08',
    );
    inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
  });
  expect(button('Apply').disabled).toBe(false);
  await act(async () => button('Apply').click());
  expect(updated).toEqual({ ...filters, start: '2025-11-08' });
});
it('cancel discards custom dates', async () => {
  let updated: Filters | undefined;
  await mount((next) => {
    updated = next;
  });
  await act(async () => {
    const input = document.querySelector<HTMLInputElement>('input[type="date"]');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(
      input,
      '2026-10-01',
    );
    input?.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => button('Cancel').click());
  expect(updated).toBeUndefined();
  expect(document.querySelector('[role="dialog"]')).toBeNull();
});

it.each([
  ['2026-11-09', '2026-11-08'],
  ['2026-11-01', '9999-12-31'],
  ['', '2026-11-08'],
])('rejects invalid bounds %s to %s', async (start, end) => {
  let updated: Filters | undefined;
  await mount((next) => {
    updated = next;
  });
  const inputs = Array.from(document.querySelectorAll<HTMLInputElement>('input[type="date"]'));
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    setter?.call(inputs[0], start);
    inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
    setter?.call(inputs[1], end);
    inputs[1].dispatchEvent(new Event('input', { bubbles: true }));
  });
  expect(button('Apply').disabled).toBe(true);
  expect(updated).toBeUndefined();
});
