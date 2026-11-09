// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import type { Filters, Property, Report } from '../utils/types';
import { ReportExport } from './ReportExport';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
afterEach(async () => {
  await act(async () => root?.unmount());
  document.body.replaceChildren();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
const property: Property = {
  id: 'property/unsafe:1',
  name: 'Website',
  kind: 'public',
  origins: [],
  route_patterns: [],
  event_allowlist: {},
  utm_parameters: [],
  enabled: true,
};
const filters: Filters = {
  start: '2026-11-01',
  end: '2026-11-08',
  path: '',
  event: '',
  country: '',
  region: '',
  city: '',
};
const report: Report = {
  totals: { pageviews: 0, visitors: 0, sessions: 0, events: 0 },
  series: [],
  breakdowns: {
    path: [],
    referrer: [],
    utm_source: [],
    utm_medium: [],
    utm_campaign: [],
    browser: [],
    os: [],
    device: [],
    country: [],
    region: [],
    city: [],
    event: [],
  },
  recent: { visitors: 0, events: [] },
};
async function mount(data: Report | null = report, busy = false) {
  const container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(async () =>
    root.render(<ReportExport property={property} report={data} filters={filters} busy={busy} />),
  );
  const button = container.querySelector('button');
  expect(button).not.toBeNull();
  return button as HTMLButtonElement;
}

it('downloads the authorized report with a safe filename and releases its browser resources', async () => {
  vi.useFakeTimers();
  let blob: Blob | undefined;
  const create = vi.spyOn(URL, 'createObjectURL').mockImplementation((value) => {
    blob = value as Blob;
    return 'blob:analytics-export';
  });
  const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  let filename = '';
  let href = '';
  let connected = false;
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    filename = this.download;
    href = this.href;
    connected = this.isConnected;
  });
  const button = await mount();
  expect(button.disabled).toBe(false);
  expect(button.textContent).toBe('Export CSV');
  await act(async () => button.click());
  expect(filename).toBe('analytics-property_unsafe_1-2026-11-01-2026-11-08.csv');
  expect(href).toBe('blob:analytics-export');
  expect(connected).toBe(true);
  expect(blob?.type).toBe('text/csv;charset=utf-8');
  expect(await blob?.text()).toContain('"metadata","property_id","","property/unsafe:1"');
  expect(await blob?.text()).toContain('"total","","","","","pageviews",0');
  expect(document.querySelector('a[download]')).toBeNull();
  await act(async () => vi.runAllTimers());
  expect(revoke).toHaveBeenCalledWith('blob:analytics-export');
  expect(create).toHaveBeenCalledTimes(1);
});

it.each([
  [null, false],
  [report, true],
] as const)('disables export without a current completed report (%j, %j)', async (data, busy) => {
  const create = vi.spyOn(URL, 'createObjectURL');
  const button = await mount(data, busy);
  expect(button.disabled).toBe(true);
  await act(async () => button.click());
  expect(create).not.toHaveBeenCalled();
});

it('shows a translated actionable error if the browser cannot create the download', async () => {
  vi.spyOn(URL, 'createObjectURL').mockImplementation(() => {
    throw new Error('Browser download unavailable');
  });
  const button = await mount();
  await act(async () => button.click());
  expect(document.querySelector('[role="alert"]')?.textContent).toBe(
    'CSV export failed. Try again.',
  );
  expect(document.querySelector('a[download]')).toBeNull();
});
