import type { TrackingProperty } from './tracker';
export type Property = TrackingProperty & { name: string; origins: string[]; enabled: boolean };
export type PropertyInput = Omit<Property, 'id'>;
export type Breakdown = { value: string; label: string; count: number };
export const DIMENSIONS = [
  'path',
  'referrer',
  'utm_source',
  'utm_medium',
  'utm_campaign',
  'browser',
  'os',
  'device',
  'country',
  'region',
  'city',
  'event',
] as const;
export type Dimension = (typeof DIMENSIONS)[number];
export type Filters = {
  start: string;
  end: string;
  path: string;
  event: string;
  country: string;
  region: string;
  city: string;
};
export type Report = {
  totals: { pageviews: number; visitors: number; sessions: number; events: number };
  series: { date: string; pageviews: number; events: number }[];
  breakdowns: Record<Dimension, Breakdown[]> & Record<string, Breakdown[]>;
  recent: {
    visitors: number;
    events: {
      event_id: string;
      kind: string;
      path: string;
      name: string | null;
      created_at: string;
      country: string;
      region: string;
      city: string;
      country_name?: string;
      region_name?: string;
      city_name?: string;
    }[];
  };
};
export type GeoStatus = {
  enabled: boolean;
  available: boolean;
  status: string;
  age_days: number | null;
};
