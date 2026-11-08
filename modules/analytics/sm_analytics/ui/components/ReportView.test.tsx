// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import type { Report } from '../utils/types';
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
    const report: Report = {
      totals: { pageviews: 1, visitors: 1, sessions: 1, events: 0 },
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
      recent: {
        visitors: 1,
        events: [
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
        ],
      },
    };
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
