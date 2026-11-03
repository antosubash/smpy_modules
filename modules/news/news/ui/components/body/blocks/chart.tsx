/**
 * A chart of a small series the writer types in.
 *
 * The palette had none for a long time, and the reason was a good one: a chart
 * usually means a charting library, and this module renders on the public
 * article page of a host that may have installed nothing else — the same rule
 * that keeps `Code` from being syntax-highlighted. Shipping fifty kilobytes of
 * JavaScript onto every article that carries three numbers is not a trade a
 * newsroom should make on the reader's behalf.
 *
 * What was wrong was treating that as an argument against charts. Bars are
 * `<div>`s of a width, a line is a `<polyline>`, and neither needs a runtime
 * dependency at all. So there is none here: no library, no import beyond the
 * arithmetic next door in `./chartScale.ts`.
 *
 * The figures come with it. The chart itself is `aria-hidden` and a `<details>`
 * holds the real table — a reader on a screen reader gets the numbers rather
 * than a description of a picture of them, and a sighted reader can open it to
 * check what a bar actually says. That is the "table of the figures" this
 * module's README argued was the honest version; it is here *as well as* the
 * chart rather than instead of it.
 */

import type { ComponentConfig } from '@puckeditor/core';

import { keys, useT } from '../../../utils/i18n';

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
import { itemKey } from './lines';

export interface ChartProps {
  title: string;
  kind: 'bar' | 'line';
  series: string;
  caption: string;
}

/** Categories against each other. Horizontal, so a category keeps its name in
 *  running text at the reader's own font size — a vertical bar chart has to
 *  turn its labels on their side the moment one of them is a word. */
function BarChart({ points }: { points: ChartPoint[] }) {
  const domain = chartDomain(points, true);
  return (
    <div className="space-y-2">
      {points.map((point, index) => {
        const { left, width } = barSpan(point.value, domain);
        return (
          <div
            key={itemKey(point.label, index)}
            className="grid grid-cols-[minmax(0,7rem)_1fr_auto] items-center gap-3"
          >
            <span className="truncate text-sm">{point.label}</span>
            <span className="h-4 rounded bg-muted">
              <span
                className="block h-full rounded bg-primary"
                style={{ marginLeft: `${left}%`, width: `${width}%` }}
              />
            </span>
            <span className="text-sm tabular-nums">{point.display}</span>
          </div>
        );
      })}
    </div>
  );
}

/** A shape over time. Colours come from `currentColor` rather than `stroke-*`
 *  utilities, so the block does not depend on which Tailwind colour helpers a
 *  host's build happens to emit. */
function LineChart({ points }: { points: ChartPoint[] }) {
  const domain = chartDomain(points, false);
  const coords = linePoints(points, domain);
  const zeroY = baselineY(domain);
  const last = points[points.length - 1];
  return (
    <div className="text-primary">
      {/* Hidden here as well as on the wrapper the block renders it into: an
          untitled `<svg>` is an unlabelled image to anything that finds it on
          its own, and the figures below are the label. */}
      <svg
        viewBox={`0 0 ${LINE_BOX.width} ${LINE_BOX.height}`}
        className="h-auto w-full"
        aria-hidden="true"
        focusable="false"
      >
        {zeroY !== null && (
          <line
            x1={LINE_BOX.pad}
            x2={LINE_BOX.width - LINE_BOX.pad}
            y1={zeroY}
            y2={zeroY}
            stroke="currentColor"
            strokeOpacity={0.3}
          />
        )}
        <polyline
          points={polylinePoints(coords)}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          // Without this the stroke scales with the viewBox, so the same chart
          // is hairline on a phone and heavy on a wide screen.
          vectorEffect="non-scaling-stroke"
        />
        {coords.map((coord, index) => (
          <circle
            key={itemKey(points[index].label, index)}
            cx={coord.x}
            cy={coord.y}
            r={3}
            fill="currentColor"
          />
        ))}
      </svg>
      {/* The ends only. Every label under a line chart in a narrow column
          overlaps into an unreadable band; the figures table carries the rest. */}
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{points[0].label}</span>
        {points.length > 1 && <span>{last.label}</span>}
      </div>
    </div>
  );
}

function FiguresTable({ points }: { points: ChartPoint[] }) {
  const { t } = useT();
  return (
    <div className="overflow-x-auto">
      <table className="mt-2 w-full border-collapse text-sm">
        <thead>
          <tr>
            <th scope="col" className="border-b-2 px-3 py-2 text-left font-semibold">
              {t(keys.news.blocks.chart.column_label)}
            </th>
            <th scope="col" className="border-b-2 px-3 py-2 text-left font-semibold">
              {t(keys.news.blocks.chart.column_value)}
            </th>
          </tr>
        </thead>
        <tbody>
          {points.map((point, index) => (
            <tr key={itemKey(point.label, index)}>
              <td className="border-b px-3 py-2">{point.label}</td>
              <td className="border-b px-3 py-2 tabular-nums">{point.display}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export const ChartBlock: ComponentConfig<ChartProps> = {
  label: keys.news.blocks.chart.label,
  fields: {
    title: { type: 'text', label: keys.news.blocks.common.heading_optional },
    kind: {
      type: 'radio',
      label: keys.news.blocks.chart.kind,
      options: [
        { label: keys.news.blocks.chart.kind_bar, value: 'bar' },
        { label: keys.news.blocks.chart.kind_line, value: 'line' },
      ],
    },
    series: { type: 'textarea', label: keys.news.blocks.chart.series },
    caption: { type: 'text', label: keys.news.blocks.common.caption_optional },
  },
  defaultProps: { title: '', kind: 'bar', series: '', caption: '' },
  // A component rather than JSX inline, because the disclosure's own word is
  // translated and Puck calls `render` as a plain function.
  render: ({ caption, kind, series, title }) => (
    <ChartRender caption={caption} kind={kind} series={series} title={title} />
  ),
};

function ChartRender({ caption, kind, series, title }: ChartProps) {
  const { t } = useT();
  const points = parseSeries(series);
  if (points.length === 0) return <></>;
  return (
    <figure className="my-8">
      {title && (
        <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </p>
      )}
      {/* Hidden from a screen reader because the table below says the same
          thing properly. Reading out a row of bars is reading out the numbers
          twice, in the worse order. */}
      <div aria-hidden="true">
        {kind === 'line' ? <LineChart points={points} /> : <BarChart points={points} />}
      </div>
      {/* Closed by default and open without JavaScript — a disclosure the
          browser implements, not one this module would have to ship. */}
      <details className="mt-3">
        <summary className="cursor-pointer text-xs text-muted-foreground">
          {t(keys.news.blocks.chart.figures)}
        </summary>
        <FiguresTable points={points} />
      </details>
      {caption && <figcaption className="mt-2 text-sm text-muted-foreground">{caption}</figcaption>}
    </figure>
  );
}
