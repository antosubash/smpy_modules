import type { Filters, Property, Report } from './types';

function cell(value: string | number): string {
  if (typeof value === 'number') return String(value);
  // Spreadsheet apps may ignore leading whitespace/control characters before formulas.
  const safe = /^[\s\p{Cc}\p{Cf}]*[=+\-@]|^[\p{Cc}]/u.test(value) ? `'${value}` : value;
  return `"${safe.replaceAll('"', '""')}"`;
}

export function reportCsv(property: Property, filters: Filters, report: Report): string {
  const rows: (string | number)[][] = [
    ['section', 'dimension', 'date', 'value', 'label', 'metric', 'count'],
  ];
  const metadata = {
    property_id: property.id,
    property_name: property.name,
    property_kind: property.kind,
    start_utc: filters.start,
    end_utc: filters.end,
    date_bounds: 'inclusive_utc',
    scope: 'current_report',
    breakdown_limit: 'top_50_per_dimension',
  };
  for (const [key, value] of Object.entries(metadata))
    rows.push(['metadata', key, '', value, '', '', '']);
  for (const dimension of ['path', 'event', 'country', 'region', 'city'] as const) {
    const value = filters[dimension];
    const unknown = dimension !== 'path' && dimension !== 'event' && value === '__unknown__';
    rows.push([
      'filter',
      dimension,
      '',
      unknown ? '' : value,
      unknown ? 'Unknown' : value || 'All',
      '',
      '',
    ]);
  }
  for (const [metric, count] of Object.entries(report.totals))
    rows.push(['total', '', '', '', '', metric, count]);
  for (const day of report.series)
    for (const metric of ['pageviews', 'events'] as const)
      rows.push(['series', '', day.date, '', '', metric, day[metric]]);
  for (const [dimension, breakdown] of Object.entries(report.breakdowns))
    for (const row of breakdown)
      rows.push(['breakdown', dimension, '', row.value, row.label, '', row.count]);
  return `\uFEFF${rows.map((row) => row.map(cell).join(',')).join('\r\n')}\r\n`;
}
