import { describe, expect, it } from 'vitest';

import { ChartBlock } from './chart';
import { renderBlock } from './renderBlock';

const SERIES = 'North | 12\nSouth | 9\nEast | 21';

describe('Chart', () => {
  it('renders nothing without a series', () => {
    expect(renderBlock(ChartBlock)).toBe('');
    expect(renderBlock(ChartBlock, { series: 'North | tbc' })).toBe('');
  });

  it('draws a bar per row, labelled', () => {
    const markup = renderBlock(ChartBlock, { series: SERIES });
    expect(markup).toContain('North');
    expect(markup).toContain('South');
    expect(markup).toContain('East');
    expect(markup.match(/width:/g)).toHaveLength(3);
  });

  it('sizes each bar against the largest figure', () => {
    // 12 of 21 is 57.14% — the bar has to say the same thing the number does.
    const markup = renderBlock(ChartBlock, { series: SERIES });
    expect(markup).toContain('width:57.14%');
    expect(markup).toContain('width:100%');
  });

  it('shows the figure as the writer typed it', () => {
    const markup = renderBlock(ChartBlock, { series: 'Share | 45%' });
    expect(markup).toContain('45%');
  });

  it('carries the figures as a real table', () => {
    // The honest version of a chart: the numbers, not a description of a
    // picture of them.
    const markup = renderBlock(ChartBlock, { series: SERIES });
    expect(markup).toContain('<table');
    expect(markup).toContain('scope="col"');
    expect(markup).toContain('<td class="border-b px-3 py-2">North</td>');
  });

  it('puts the table behind a disclosure the browser implements', () => {
    // No JavaScript ships with this block, so the fold cannot be one it
    // manages itself.
    const markup = renderBlock(ChartBlock, { series: SERIES });
    expect(markup).toContain('<details');
    expect(markup).toContain('<summary');
  });

  it('hides the drawing from a screen reader, which has the table instead', () => {
    // Reading out a row of bars is reading out the numbers twice, in the
    // worse order.
    expect(renderBlock(ChartBlock, { series: SERIES })).toContain('aria-hidden="true"');
  });

  it('draws a line through every point when asked for one', () => {
    const markup = renderBlock(ChartBlock, { series: SERIES, kind: 'line' });
    expect(markup).toContain('<polyline');
    expect(markup.match(/<circle/g)).toHaveLength(3);
    expect(markup).not.toContain('width:');
  });

  it('labels only the ends of a line', () => {
    // Every label under a line chart in a narrow column overlaps into an
    // unreadable band; the figures table carries the rest.
    const markup = renderBlock(ChartBlock, { series: SERIES, kind: 'line' });
    expect(markup).toContain('>North<');
    expect(markup).toContain('>East<');
    expect(markup.match(/>South</g)).toHaveLength(1); // the table row only
  });

  it('marks zero on a line that crosses it, and not on one that does not', () => {
    const crossing = renderBlock(ChartBlock, {
      series: 'Q1 | -4\nQ2 | 9',
      kind: 'line',
    });
    expect(crossing).toContain('<line');
    expect(renderBlock(ChartBlock, { series: SERIES, kind: 'line' })).not.toContain('<line');
  });

  it('needs no charting library to do any of it', () => {
    // The whole reason the palette had no chart. Bars are divs of a width and
    // a line is a polyline; neither carries a runtime dependency onto the
    // public page of a host that installed nothing else.
    const markup = renderBlock(ChartBlock, { series: SERIES, kind: 'line' });
    expect(markup).toContain('<svg');
    expect(markup).not.toContain('<script');
  });

  it('shows the heading and caption only when they are written', () => {
    const bare = renderBlock(ChartBlock, { series: SERIES });
    expect(bare).not.toContain('<figcaption');
    const dressed = renderBlock(ChartBlock, {
      series: SERIES,
      title: 'Sensors by site',
      caption: 'Source: the survey',
    });
    expect(dressed).toContain('Sensors by site');
    expect(dressed).toContain('<figcaption');
  });
});
