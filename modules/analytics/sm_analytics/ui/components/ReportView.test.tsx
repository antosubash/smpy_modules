// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import type { Filters, Report } from '../utils/types';
import { ReportView } from './ReportView';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it.each([
  [
    { city_name: 'London', region_name: 'England', country_name: 'United Kingdom' },
    'London, England, United Kingdom',
  ],
  [{ city_name: '', region_name: 'England', country_name: '' }, '2643743, England, GB'],
  [{}, '2643743, GB-ENG, GB'],
])(
  'recent activity prefers readable location names with per-field code fallback: %j',
  async (names, expected) => {
    const report = makeReport();
    report.recent.events = [
      {
        event_id: 'event',
        kind: 'pageview',
        path: '/',
        name: null,
        created_at: '2026-11-08T12:00:00Z',
        country: 'GB',
        region: 'GB-ENG',
        city: '2643743',
        ...names,
      },
    ];
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    try {
      await act(async () =>
        root.render(
          <ReportView
            report={report}
            filters={{ start: '', end: '', path: '', event: '', country: '', region: '', city: '' }}
            onFilter={() => {}}
          />,
        ),
      );
      const cells = Array.from(container.querySelectorAll('td'));
      expect(cells.at(-1)?.textContent).toBe(expected);
    } finally {
      await act(async () => root.unmount());
      container.remove();
    }
  },
);

const filters: Filters = {
  start: '2026-11-01',
  end: '2026-11-08',
  path: '',
  event: '',
  country: 'GB',
  region: 'GB-ENG',
  city: '2643743',
};
function makeReport(): Report {
  return {
    totals: { pageviews: 1200, visitors: 800, sessions: 900, events: 42 },
    series: [{ date: '2026-11-08', pageviews: 12, events: 3 }],
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
}
const roots: ReturnType<typeof createRoot>[] = [];
afterEach(async () => {
  await act(async () =>
    roots.splice(0).forEach((root) => {
      root.unmount();
    }),
  );
  document.body.replaceChildren();
});
async function renderReport(report = makeReport(), onFilter = vi.fn()) {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  await act(async () =>
    root.render(<ReportView report={report} filters={filters} onFilter={onFilter} />),
  );
  return container;
}
async function activate(container: HTMLElement, text: string) {
  const button = Array.from(container.querySelectorAll('button')).find(
    (b) => b.textContent === text,
  );
  expect(button, `button ${text}`).toBeDefined();
  await act(async () => {
    button?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }));
    button?.click();
  });
}

it('switches the daily chart locally between the supplied pageviews and events', async () => {
  const onFilter = vi.fn();
  const container = await renderReport(makeReport(), onFilter);
  expect(container.querySelector('[aria-label="Chart metric"]')).not.toBeNull();
  await activate(container, 'Custom events');
  const chart = container.querySelector('[data-slot="chart"]');
  expect(chart?.getAttribute('aria-label')).toBe('Custom events');
  expect(container.querySelector('details tbody')?.textContent).toBe('2026-11-083');
  expect(container.querySelector('button[aria-pressed="true"]')?.textContent).toBe('Custom events');
  await activate(container, 'Pageviews');
  expect(chart?.getAttribute('aria-label')).toBe('Pageviews');
  expect(container.querySelector('details tbody')?.textContent).toBe('2026-11-0812');
  expect(onFilter).not.toHaveBeenCalled();
});

it('groups sources in tabs and expands only returned ranking rows', async () => {
  const report = makeReport();
  report.breakdowns.path = Array.from({ length: 12 }, (_, i) => ({
    value: `/page-${i}`,
    label: `/page-${i}`,
    count: 24 - i,
  }));
  report.breakdowns.referrer = [
    { value: 'example.org', label: 'example.org', count: 24 },
    { value: 'blog.example', label: 'blog.example', count: 6 },
  ];
  report.breakdowns.utm_source = [{ value: 'newsletter', label: 'newsletter', count: 6 }];
  const onFilter = vi.fn();
  const container = await renderReport(report, onFilter);
  expect(container.textContent).not.toContain('/page-10');
  const sources = container.querySelector('[role="tabpanel"] table');
  expect(
    Array.from(sources?.querySelectorAll('span[aria-hidden]') || []).map(
      (bar) => (bar as HTMLElement).style.width,
    ),
  ).toEqual(['100%', '25%']);
  await activate(container, 'Show more');
  expect(container.textContent).toContain('/page-11');
  await activate(container, 'Show less');
  expect(container.textContent).not.toContain('/page-10');
  await activate(container, 'Campaign sources');
  const visiblePanels = Array.from(container.querySelectorAll('[role="tabpanel"]')).filter(
    (p) => !p.hasAttribute('hidden'),
  );
  expect(visiblePanels.some((p) => p.textContent?.includes('newsletter'))).toBe(true);
  expect(container.querySelector('button[value="newsletter"]')).toBeNull();
  expect(onFilter).not.toHaveBeenCalled();
});

it('keeps unsupported dimensions and event properties informational', async () => {
  const report = makeReport();
  report.breakdowns.browser = [{ value: 'Firefox', label: 'Firefox', count: 8 }];
  report.breakdowns['property:format'] = [{ value: 'pdf', label: 'PDF', count: 4 }];
  const container = await renderReport(report);
  await activate(container, 'Event property: format');
  expect(container.textContent).toContain('PDF');
  expect(
    Array.from(container.querySelectorAll('button')).some((b) =>
      ['PDF', 'Firefox'].includes(b.textContent || ''),
    ),
  ).toBe(false);
});

it.each([
  ['country', 'Countries', 'AT', { country: 'AT', region: '', city: '' }],
  ['region', 'Regions', 'AT-9', { country: 'GB', region: 'AT-9', city: '' }],
  ['city', 'Cities', '', { country: 'GB', region: 'GB-ENG', city: '__unknown__' }],
] as const)(
  'filters %s with Unknown semantics and clears only descendants',
  async (dimension, tab, value, expected) => {
    const report = makeReport();
    report.breakdowns[dimension] = [{ value, label: value, count: 4 }];
    const onFilter = vi.fn();
    const container = await renderReport(report, onFilter);
    if (dimension !== 'country') await activate(container, tab);
    await activate(container, value || 'Unknown');
    expect(onFilter).toHaveBeenCalledWith({ ...filters, ...expected });
  },
);

it('connects ranking tabs and panels to existing accessible labels', async () => {
  const report = makeReport();
  report.series = [];
  const container = await renderReport(report);
  for (const panel of container.querySelectorAll('[role="tabpanel"]')) {
    const label = panel.getAttribute('aria-labelledby');
    expect(
      label && document.getElementById(label),
      'tab panel has an existing trigger',
    ).toBeTruthy();
  }
  for (const tab of container.querySelectorAll('[role="tab"]')) {
    const controls = tab.getAttribute('aria-controls');
    expect(
      controls && document.getElementById(controls),
      'tab controls an existing panel',
    ).toBeTruthy();
  }
});
