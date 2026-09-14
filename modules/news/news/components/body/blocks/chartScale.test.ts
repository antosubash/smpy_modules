import { describe, expect, it } from 'vitest';

import {
  barSpan,
  baselineY,
  type ChartPoint,
  chartDomain,
  LINE_BOX,
  linePoints,
  parseSeries,
  polylinePoints,
} from './chartScale';

function points(...values: number[]): ChartPoint[] {
  return values.map((value) => ({ label: String(value), value, display: String(value) }));
}

describe('parseSeries', () => {
  it('reads a label and a value per line', () => {
    expect(parseSeries('2019 | 12\n2020 | 15')).toEqual([
      { label: '2019', value: 12, display: '12' },
      { label: '2020', value: 15, display: '15' },
    ]);
  });

  it('keeps the value exactly as typed for the figures', () => {
    // A writer who wrote "45%" gets that back, not a bare number that has
    // quietly dropped what it was measuring.
    const [point] = parseSeries('Share | 45%');
    expect(point.display).toBe('45%');
    expect(point.value).toBe(45);
  });

  it('reads through a currency symbol and a thousands separator', () => {
    expect(parseSeries('Cost | $1,200').map((p) => p.value)).toEqual([1200]);
  });

  it('reads a negative value as negative', () => {
    expect(parseSeries('Change | -4.5').map((p) => p.value)).toEqual([-4.5]);
  });

  it('reads a European decimal comma as a decimal point', () => {
    // "1,5" is one and a half, not fifteen — a trailing 1-2 digit comma with
    // no "." in the cell is a decimal separator, not a thousands one.
    expect(parseSeries('Growth | 1,5').map((p) => p.value)).toEqual([1.5]);
    expect(parseSeries('Loss | -2,75').map((p) => p.value)).toEqual([-2.75]);
    // Display keeps exactly what was typed either way.
    expect(parseSeries('Growth | 1,5')[0].display).toBe('1,5');
  });

  it('still reads a thousands-separator comma as a thousands separator', () => {
    // Three or more digits after the comma, or a "." already present,
    // disambiguates it from the decimal case above.
    expect(parseSeries('Cost | 1,234').map((p) => p.value)).toEqual([1234]);
    expect(parseSeries('Cost | 1,234.5').map((p) => p.value)).toEqual([1234.5]);
  });

  it('reads both separator conventions when the grouping is unambiguous', () => {
    expect(parseSeries('Cost | 1.234,5').map((p) => p.value)).toEqual([1234.5]);
    expect(parseSeries('Cost | €1.234.567,89').map((p) => p.value)).toEqual([1234567.89]);
    expect(parseSeries('Cost | $1,234,567.89').map((p) => p.value)).toEqual([1234567.89]);
  });

  it('drops a figure with both separators in no recognisable order', () => {
    // "1.5,25" used to strip the comma and plot 1.525 — a real-looking number
    // the writer never typed, which is the one outcome worse than losing the
    // row. Not a number anyone writes on purpose, so it is not a number.
    expect(parseSeries('Growth | 1.5,25')).toEqual([]);
    expect(parseSeries('Growth | 12.34,56')).toEqual([]);
  });

  it('reads a typographic minus sign as negative', () => {
    // U+2212, not the ASCII hyphen-minus a keyboard types — stripped like
    // ordinary punctuation would turn this positive instead.
    expect(parseSeries('Change | −4.5').map((p) => p.value)).toEqual([-4.5]);
  });

  it('drops a row whose value is not a number', () => {
    // Plotting a typo as zero would draw a bar of length nothing, which reads
    // as a real measurement of nothing.
    expect(parseSeries('North | 12\nSouth | tbc\nEast |').map((p) => p.label)).toEqual(['North']);
  });

  it('has nothing to plot for an empty field', () => {
    expect(parseSeries('')).toEqual([]);
    expect(parseSeries(undefined)).toEqual([]);
  });
});

describe('chartDomain', () => {
  it('always includes zero for bars', () => {
    // A bar's length is its value; an axis starting anywhere else exaggerates
    // every difference on it.
    expect(chartDomain(points(100.1, 100.4), true)).toEqual({ min: 0, max: 100.4 });
  });

  it('hugs the data for a line', () => {
    // A line shows a shape. Forcing zero in flattens the only thing a series
    // moving between 100.1 and 100.4 was drawn to show.
    expect(chartDomain(points(100.1, 100.4), false)).toEqual({ min: 100.1, max: 100.4 });
  });

  it('stretches below zero when the numbers go there', () => {
    expect(chartDomain(points(-4, 9), true)).toEqual({ min: -4, max: 9 });
  });

  it('pads a series that does not move, rather than dividing by nothing', () => {
    expect(chartDomain(points(7, 7), false)).toEqual({ min: 6, max: 8 });
    expect(chartDomain(points(0, 0), true)).toEqual({ min: -1, max: 1 });
  });

  it('has a usable range with no points at all', () => {
    expect(chartDomain([], true)).toEqual({ min: 0, max: 1 });
  });
});

describe('barSpan', () => {
  const positive = { min: 0, max: 200 };

  it('measures an all-positive bar from the left edge', () => {
    expect(barSpan(50, positive)).toEqual({ left: 0, width: 25 });
    expect(barSpan(200, positive)).toEqual({ left: 0, width: 100 });
  });

  it('draws a zero as no bar at all', () => {
    expect(barSpan(0, positive)).toEqual({ left: 0, width: 0 });
  });

  it('draws a negative value to the left of the baseline', () => {
    // Not as a positive one of the same length, which is what measuring from
    // the left edge would produce.
    const crossing = { min: -10, max: 10 };
    expect(barSpan(-5, crossing)).toEqual({ left: 25, width: 25 });
    expect(barSpan(5, crossing)).toEqual({ left: 50, width: 25 });
  });
});

describe('linePoints', () => {
  const domain = { min: 0, max: 10 };

  it('spreads the points evenly between the padded edges', () => {
    const coords = linePoints(points(0, 5, 10), domain);
    expect(coords.map((c) => c.x)).toEqual([
      LINE_BOX.pad,
      LINE_BOX.width / 2,
      LINE_BOX.width - LINE_BOX.pad,
    ]);
  });

  it('counts upwards even though SVG counts down', () => {
    const [low, high] = linePoints(points(0, 10), domain);
    expect(high.y).toBeLessThan(low.y);
    expect(low.y).toBe(LINE_BOX.height - LINE_BOX.pad);
    expect(high.y).toBe(LINE_BOX.pad);
  });

  it('puts a lone point in the middle', () => {
    // Hard against the left edge it reads as the start of a line that failed
    // to draw.
    expect(linePoints(points(5), domain)[0].x).toBe(LINE_BOX.width / 2);
  });

  it('formats coordinates for the attribute a polyline wants', () => {
    expect(
      polylinePoints([
        { x: 1, y: 2 },
        { x: 3, y: 4 },
      ]),
    ).toBe('1,2 3,4');
  });
});

describe('baselineY', () => {
  it('marks zero when the series crosses it', () => {
    const y = baselineY({ min: -10, max: 10 });
    expect(y).toBe(LINE_BOX.height / 2);
  });

  it('draws no rule when zero is outside the range', () => {
    // A line along the bottom of an all-positive chart says nothing.
    expect(baselineY({ min: 0, max: 10 })).toBeNull();
    expect(baselineY({ min: 2, max: 10 })).toBeNull();
    expect(baselineY({ min: -10, max: 0 })).toBeNull();
  });
});
