// @vitest-environment happy-dom
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { MeterUsage } from '../utils/types';
import { UsageCard } from './UsageCard';

(globalThis as unknown as { React: unknown }).React = React;

function meter(overrides: Partial<MeterUsage>): MeterUsage {
  return {
    meter: 'exports.monthly',
    kind: 'counter',
    unit: 'count',
    label_key: '',
    used: 0,
    limit: null,
    period_start: '2026-10-01T00:00:00Z',
    period_end: '2026-11-01T00:00:00Z',
    holds: null,
    ...overrides,
  };
}

function render(usage: MeterUsage[]): Document {
  const markup = renderToStaticMarkup(<UsageCard usage={usage} />);
  return new DOMParser().parseFromString(`<div>${markup}</div>`, 'text/html');
}

function row(doc: Document, key: string): Element {
  const found = doc.querySelector(`[data-meter="${key}"]`);
  if (!found) throw new Error(`no row for ${key}`);
  return found;
}

describe('UsageCard', () => {
  it('renders nothing when no meter is limited or used', () => {
    expect(renderToStaticMarkup(<UsageCard usage={[]} />)).toBe('');
  });

  it('shows "Unlimited" and no bar when the plan sets no limit', () => {
    const doc = render([meter({ used: 1200 })]);
    const item = row(doc, 'exports.monthly');
    expect(item.textContent).toContain('1,200 used');
    expect(item.textContent).toContain('Unlimited');
    expect(item.querySelector('[role="progressbar"]')).toBeNull();
  });

  it('shows used of limit and when a counter resets', () => {
    const doc = render([meter({ used: 3, limit: 10 })]);
    const item = row(doc, 'exports.monthly');
    expect(item.textContent).toContain('3 of 10');
    expect(item.textContent).toContain('Resets Nov 1, 2026');
    const bar = item.querySelector('[role="progressbar"]');
    expect(bar?.getAttribute('aria-valuenow')).toBe('30');
    expect(bar?.getAttribute('data-tone')).toBe('normal');
  });

  it('formats bytes and says a gauge is in use rather than resetting', () => {
    const doc = render([
      meter({
        meter: 'storage.bytes',
        kind: 'gauge',
        unit: 'bytes',
        used: 1_500_000,
        limit: 10_000_000_000,
        period_start: null,
        period_end: null,
        holds: 2,
      }),
    ]);
    const item = row(doc, 'storage.bytes');
    expect(item.textContent).toContain('1.5 MB of 10 GB');
    expect(item.textContent).toContain('In use now');
    expect(item.textContent).not.toContain('Resets');
  });

  it('takes the warning colour at 90% and says when the limit is reached', () => {
    const doc = render([
      meter({ meter: 'a', used: 9, limit: 10 }),
      meter({ meter: 'b', used: 12, limit: 10 }),
      meter({ meter: 'c', used: 8, limit: 10 }),
    ]);
    const tone = (key: string) =>
      row(doc, key).querySelector('[role="progressbar"]')?.getAttribute('data-tone');
    expect([tone('a'), tone('b'), tone('c')]).toEqual(['warning', 'over', 'normal']);
    expect(row(doc, 'a').textContent).toContain('Almost at the limit');
    expect(row(doc, 'b').textContent).toContain('Limit reached');
    expect(row(doc, 'b').querySelector('[role="progressbar"]')?.getAttribute('aria-valuenow')).toBe(
      '100',
    );
  });

  it("labels a meter from the consumer's key, falling back to the meter key", () => {
    const doc = render([meter({ label_key: 'nowhere.meters.exports' })]);
    expect(row(doc, 'exports.monthly').textContent).toContain('exports.monthly');
    expect(row(doc, 'exports.monthly').textContent).not.toContain('nowhere.meters');
  });
});
