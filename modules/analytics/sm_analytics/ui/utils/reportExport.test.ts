import { expect, it } from 'vitest';
import { reportCsv } from './reportExport';
import type { Filters, Property, Report } from './types';

const property: Property = {
  id: 'property-1',
  name: 'Österreich, "Website"',
  kind: 'public',
  origins: [],
  route_patterns: [],
  event_allowlist: {},
  utm_parameters: [],
  enabled: true,
};
const filters: Filters = {
  start: '2026-11-01',
  end: '2026-11-08',
  path: '/guide',
  event: '',
  country: '__unknown__',
  region: '',
  city: '',
};
function report(): Report {
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
    recent: { visitors: 999, events: [] },
  };
}

it('records applied property/date/filter scope and exact totals with numeric counts', () => {
  const csv = reportCsv(property, filters, report());
  expect(
    csv.startsWith('\uFEFF"section","dimension","date","value","label","metric","count"\r\n'),
  ).toBe(true);
  expect(csv).toContain('"metadata","property_name","","Österreich, ""Website""","","",""\r\n');
  expect(csv).toContain('"metadata","start_utc","","2026-11-01","","",""\r\n');
  expect(csv).toContain('"metadata","end_utc","","2026-11-08","","",""\r\n');
  expect(csv).toContain('"metadata","scope","","current_report","","",""\r\n');
  expect(csv).toContain('"metadata","breakdown_limit","","top_50_per_dimension","","",""\r\n');
  expect(csv).toContain('"filter","path","","/guide","/guide","",""\r\n');
  expect(csv).toContain('"filter","country","","","Unknown","",""\r\n');
  expect(csv).toContain('"filter","region","","","All","",""\r\n');
  expect(csv).toContain('"total","","","","","pageviews",1200\r\n');
  expect(csv).toContain('"series","","2026-11-08","","","events",3\r\n');
});

it.each([
  '=1+1',
  '+SUM(A1)',
  '-2+3',
  '@SUM(A1)',
  '  =1',
  '\t=1',
  '\r=1',
  '\n=1',
  '\u0001=1',
  '\u200B=1',
])('neutralizes spreadsheet formulas in untrusted text: %j', (unsafe) => {
  const data = report();
  data.breakdowns.path = [{ value: unsafe, label: unsafe, count: 7 }];
  const csv = reportCsv({ ...property, name: unsafe }, { ...filters, path: unsafe }, data);
  const escaped = unsafe.replaceAll('"', '""');
  expect(csv).toContain(`"metadata","property_name","","'${escaped}","","",""\r\n`);
  expect(csv).toContain(`"filter","path","","'${escaped}","'${escaped}","",""\r\n`);
  expect(csv).toContain(`"breakdown","path","","'${escaped}","'${escaped}","",7\r\n`);
});

it('exports every returned breakdown including hidden rows and event properties, preserving CSV text', () => {
  const data = report();
  data.breakdowns.path = Array.from({ length: 12 }, (_, index) => ({
    value: `/page/${index}`,
    label: `Page ${index}`,
    count: index + 1,
  }));
  data.breakdowns['property:format'] = [
    { value: 'pdf', label: 'PDF, "guide"\r\n日本語', count: 5 },
  ];
  const csv = reportCsv(property, filters, data);
  expect(csv).toContain('"breakdown","path","","/page/11","Page 11","",12\r\n');
  expect(csv).toContain(
    '"breakdown","property:format","","pdf","PDF, ""guide""\r\n日本語","",5\r\n',
  );
  expect(csv).not.toContain('999');
});

it('exports empty reports as zero totals without inventing activity or recent rows', () => {
  const data = report();
  data.totals = { pageviews: 0, visitors: 0, sessions: 0, events: 0 };
  data.series = [];
  const csv = reportCsv(property, filters, data);
  expect(csv).toContain('"total","","","","","pageviews",0\r\n');
  expect(csv).toContain('"total","","","","","events",0\r\n');
  expect(csv).not.toContain('"series",');
  expect(csv).not.toContain('"breakdown",');
  expect(csv).not.toContain('"recent",');
});
