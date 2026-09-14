/**
 * Reading a typed series and turning it into geometry.
 *
 * Split out of `chart.tsx` because it is the whole of the chart that can be
 * wrong: a bar that starts at the wrong place or a point plotted upside down is
 * a false statement about the numbers, and none of it is reachable through a
 * render assertion. The file next door only decides what the shapes look like.
 *
 * There is no charting library behind any of this, deliberately — see
 * `./chart.tsx`.
 */

import { cells, lines } from './lines';

export interface ChartPoint {
  label: string;
  /** What the geometry is computed from. */
  value: number;
  /** The value cell exactly as typed. A writer who wrote "45%" or "$1,200"
   *  gets that back in the figures, rather than a bare number that has quietly
   *  dropped what it was measuring. */
  display: string;
}

export interface ChartDomain {
  min: number;
  max: number;
}

export interface ChartBox {
  width: number;
  height: number;
  pad: number;
}

/** The line chart's coordinate space. A viewBox rather than pixels: the SVG
 *  scales to the article column, and the numbers here never have to know how
 *  wide that is. */
export const LINE_BOX: ChartBox = { width: 320, height: 140, pad: 10 };

/** Everything that is not part of a number. Stripped before parsing so a
 *  currency symbol, a percent sign or a thousands separator does not cost the
 *  writer the row — they typed a figure, and the figure is legible. */
const NOT_NUMERIC = /[^0-9.+-]/g;

/** Typographic minus signs a writer's keyboard or autocorrect might produce
 *  (U+2212 minus sign, U+2012–U+2015 figure/en/em dashes) are not the ASCII
 *  hyphen-minus `NOT_NUMERIC` keeps — stripped like any other punctuation,
 *  they would turn a negative figure positive rather than dropping the row,
 *  which is the one wrong answer worse than losing it. Folded onto `-` first. */
const TYPOGRAPHIC_MINUS = /[−‒-―]/g;

/** A trailing comma with one or two digits after it, and no `.` anywhere in
 *  the cell, reads as a decimal separator (`1,5`) — the reading a
 *  European-locale writer intends. Anything else (`1,200`, `1,234.5`) is a
 *  thousands separator, which `NOT_NUMERIC` already strips correctly.
 *  Ambiguous past this point either way, so only the one shape that would
 *  otherwise silently multiply the figure by ten (or a hundred) is caught. */
const TRAILING_DECIMAL_COMMA = /,(\d{1,2})$/;

function normalizeDigits(raw: string): string {
  const signed = raw.replace(TYPOGRAPHIC_MINUS, '-');
  if (!signed.includes('.') && TRAILING_DECIMAL_COMMA.test(signed)) {
    return signed.replace(TRAILING_DECIMAL_COMMA, '.$1');
  }
  return signed;
}

/** Two decimals. Percentages and viewBox coordinates carried to seventeen
 *  make the markup unreadable and the tests unwritable, and no screen can
 *  render the difference. */
function round(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * The series, one point per line, `label | value`.
 *
 * A row whose value is not a number is dropped rather than plotted as zero: a
 * typo would otherwise become a bar of length nothing, which reads as a real
 * measurement of nothing.
 */
export function parseSeries(text: string | undefined): ChartPoint[] {
  const points: ChartPoint[] = [];
  for (const line of lines(text)) {
    const [label, raw] = cells(line, 2);
    const display = raw.trim();
    // Emptiness is checked *after* stripping, not before: "tbc" strips to the
    // empty string, and `Number("")` is 0 — a value the writer never wrote.
    const digits = normalizeDigits(display).replace(NOT_NUMERIC, '');
    if (!digits) continue;
    const value = Number(digits);
    if (!Number.isFinite(value)) continue;
    points.push({ label, value, display });
  }
  return points;
}

/**
 * The range the chart is drawn over.
 *
 * `includeZero` is the difference between the two kinds, and it is not a
 * stylistic one. A bar's length *is* its value, so an axis that starts
 * somewhere else exaggerates every difference on it — the classic misleading
 * chart. A line shows a shape rather than a magnitude, and forcing zero into
 * the range of a series that moves between 100.1 and 100.4 flattens the only
 * thing it was drawn to show.
 */
export function chartDomain(points: ChartPoint[], includeZero: boolean): ChartDomain {
  const values = points.map((point) => point.value);
  if (values.length === 0) return { min: 0, max: 1 };
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (includeZero) {
    min = Math.min(0, min);
    max = Math.max(0, max);
  }
  // A flat series has no range to divide by. Padding it puts the line across
  // the middle of the box, which is what a series that does not move looks
  // like; collapsing it to a single row would divide by zero instead.
  if (min === max) return { min: min - 1, max: max + 1 };
  return { min, max };
}

/**
 * Where one bar starts and how far it runs, as percentages of the track.
 *
 * Measured from zero rather than from the left edge, so a negative value draws
 * to the left of the baseline instead of being rendered as a positive one.
 */
export function barSpan(value: number, domain: ChartDomain): { left: number; width: number } {
  const span = domain.max - domain.min || 1;
  const zero = ((0 - domain.min) / span) * 100;
  const point = ((value - domain.min) / span) * 100;
  return { left: round(Math.min(zero, point)), width: round(Math.abs(point - zero)) };
}

/** The plotted points, left to right. `y` is inverted — SVG counts downwards
 *  and a chart counts up. */
export function linePoints(
  points: ChartPoint[],
  domain: ChartDomain,
  box: ChartBox = LINE_BOX,
): { x: number; y: number }[] {
  const span = domain.max - domain.min || 1;
  const innerWidth = box.width - box.pad * 2;
  const innerHeight = box.height - box.pad * 2;
  return points.map((point, index) => ({
    // A single point sits in the middle rather than hard against the left
    // edge, where it would read as the start of a line that failed to draw.
    x: round(
      points.length > 1
        ? box.pad + (innerWidth / (points.length - 1)) * index
        : box.pad + innerWidth / 2,
    ),
    y: round(box.height - box.pad - ((point.value - domain.min) / span) * innerHeight),
  }));
}

/** `points` in the attribute form `<polyline>` wants. */
export function polylinePoints(coords: { x: number; y: number }[]): string {
  return coords.map((coord) => `${coord.x},${coord.y}`).join(' ');
}

/**
 * Where zero falls, or `null` when it is outside the range.
 *
 * Only drawn when the series crosses it. A rule along the bottom of a chart of
 * all-positive numbers says nothing; one through the middle of a series that
 * goes negative is the difference between a rise and a recovery.
 */
export function baselineY(domain: ChartDomain, box: ChartBox = LINE_BOX): number | null {
  if (domain.min >= 0 || domain.max <= 0) return null;
  const span = domain.max - domain.min;
  const innerHeight = box.height - box.pad * 2;
  return round(box.height - box.pad - ((0 - domain.min) / span) * innerHeight);
}
