// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';

import en from '../../../locales/en.json';
import { ReportTimeline } from './ReportTimeline';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: ReturnType<typeof createRoot>;
async function render(props: Parameters<typeof ReportTimeline>[0]) {
  root = createRoot(document.body.appendChild(document.createElement('div')));
  await act(async () => root.render(createElement(ReportTimeline, props)));
}
afterEach(() => {
  act(() => root.unmount());
  document.body.innerHTML = '';
});

const points = [
  { at: '2026-11-01T10:00:00Z', opens: 10, clicks: 2 },
  { at: '2026-11-01T11:00:00Z', opens: 5, clicks: 0 },
  { at: '2026-11-01T12:00:00Z', opens: 0, clicks: 0 },
];

describe('ReportTimeline', () => {
  it('has one row per point and a hidden caption', async () => {
    await render({ bucket: 'hour', points });
    expect(document.querySelectorAll('tbody tr')).toHaveLength(3);
    const caption = document.querySelector('caption');
    expect(caption?.className).toContain('sr-only');
    expect(caption?.textContent).toBe(
      en.report.timeline.caption.replace('{bucket}', en.report.timeline.bucket.hour),
    );
  });

  it('scales the bars to the maximum', async () => {
    await render({ bucket: 'hour', points });
    const widths = [...document.querySelectorAll<HTMLElement>('[data-bar="opens"]')].map(
      (b) => b.style.width,
    );
    expect(widths).toEqual(['100%', '50%', '0%']);
    const clicks = [...document.querySelectorAll<HTMLElement>('[data-bar="clicks"]')].map(
      (b) => b.style.width,
    );
    expect(clicks).toEqual(['20%', '0%', '0%']);
  });

  it('labels the rows in UTC and the window per bucket', async () => {
    await render({ bucket: 'hour', points });
    expect(document.body.textContent).toContain(en.report.timeline.window_hour);
    expect(document.querySelector('tbody tr th')?.textContent).toMatch(/10:00$/);
    act(() => root.unmount());
    document.body.innerHTML = '';
    await render({
      bucket: 'day',
      points: [{ at: '2026-11-01T00:00:00Z', opens: 1, clicks: 0 }],
    });
    expect(document.body.textContent).toContain(en.report.timeline.window_day);
    expect(document.body.textContent).toContain('Nov 1, 2026');
  });

  it('shows the empty state when there is no activity', async () => {
    await render({ bucket: 'hour', points: [] });
    expect(document.body.textContent).toContain(en.report.timeline.empty);
    act(() => root.unmount());
    document.body.innerHTML = '';
    await render({ bucket: 'hour', points: points.map((p) => ({ ...p, opens: 0, clicks: 0 })) });
    expect(document.body.textContent).toContain(en.report.timeline.empty);
    expect(document.querySelector('table')).toBeNull();
  });
});
