// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';

import en from '../../../locales/en.json';
import { report } from './fixture';
import { ReportStats } from './ReportStats';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: ReturnType<typeof createRoot>;
async function render(props: Parameters<typeof ReportStats>[0]) {
  root = createRoot(document.body.appendChild(document.createElement('div')));
  await act(async () => root.render(createElement(ReportStats, props)));
  return document.body.textContent ?? '';
}
afterEach(() => {
  act(() => root.unmount());
  document.body.innerHTML = '';
});

describe('ReportStats', () => {
  it('shows the opens tile: accepted unique, its rate over accepted, all messages, approx', async () => {
    const text = await render({ report: report() });
    expect(text).toContain(en.report.stats.opens);
    expect(text).toMatch(/25(\.0)?\s?%/); // 50 of 200 accepted
    expect(text).toContain(en.report.stats.rate_hint);
    expect(text).toContain(
      en.report.stats.all_messages.replace('{unique}', '60').replace('{total}', '90'),
    );
    expect(text).toContain(en.report.approx.opens);
    expect(text).toContain(en.report.approx.clicks);
  });

  it('shows the counts of every outcome', async () => {
    const text = await render({ report: report() });
    for (const label of ['recipients', 'accepted', 'failed', 'bounced', 'suppressed', 'skipped']) {
      expect(text).toContain(en.report.stats[label as keyof typeof en.report.stats]);
    }
    expect(text).toContain(en.report.stats.accepted_hint);
    expect(text).toContain('250');
    expect(text).toContain('200');
  });

  it('shows a dash for the rate when nothing was accepted', async () => {
    const text = await render({
      report: report({ sent: 0, opens_unique_accepted: 0, clicks_unique_accepted: 0 }),
    });
    expect(text).toContain('—');
    expect(text).not.toContain('NaN');
  });

  it('notes when tracking is off for a kind', async () => {
    const off = await render({ report: report({ tracking_opens: false, tracking_clicks: false }) });
    expect(off).toContain(en.report.tracking_off.opens);
    expect(off).toContain(en.report.tracking_off.clicks);
  });

  it('has no note while tracking is on', async () => {
    const on = await render({ report: report() });
    expect(on).not.toContain(en.report.tracking_off.opens);
    expect(on).not.toContain(en.report.tracking_off.clicks);
  });
});
