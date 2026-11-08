// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it } from 'vitest';
import type { Filters, Report } from '../utils/types';
import { ReportFilters } from './ReportFilters';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const containers: HTMLDivElement[] = [];
afterEach(() => {
  for (const container of containers) container.remove();
  containers.length = 0;
});
it('country drill-down clears narrower filters and distinguishes unknown from all', async () => {
  const container = document.createElement('div');
  document.body.append(container);
  containers.push(container);
  const root = createRoot(container);
  let updated: Filters | undefined;
  const filters = {
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
  await act(async () => {
    root.render(
      <ReportFilters
        value={filters}
        onChange={(next) => {
          updated = next;
        }}
        report={report}
      />,
    );
  });
  const label = Array.from(container.querySelectorAll('label')).find(
    (item) => item.textContent === 'Country',
  );
  const select = document.getElementById(label?.htmlFor ?? '') as HTMLSelectElement;
  expect(select).not.toBeNull();
  expect(Array.from(select.options).map((option) => option.value)).toEqual([
    '',
    'AT',
    '__unknown__',
  ]);
  await act(async () => {
    select.value = '__unknown__';
    select.dispatchEvent(new Event('change', { bubbles: true }));
  });
  expect(updated).toEqual({ ...filters, country: '__unknown__', region: '', city: '' });
  await act(async () => {
    root.unmount();
  });
});
