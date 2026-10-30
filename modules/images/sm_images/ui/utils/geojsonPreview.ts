/**
 * Client-side preview of a local GeoJSON file, ported from the portal.
 *
 * Only a bounded head of the file is ever read (`PREVIEW_HEAD_BYTES`), however
 * large the file is: `scanGeoJsonHead` walks it by hand and parses just the
 * first few complete features. A file that fits in the head is read whole, so
 * its feature count is exact; a larger one is `isPartial` and its count is a
 * lower bound. The server validates the real document; this only proposes a
 * property mapping and shows a sample.
 */

import {
  type DetectedMappings,
  detectPropertyMappings,
  NO_DETECTION,
  type PropertyInfo,
  type ValueType,
} from './geojsonDetect';
import { scanGeoJsonHead } from './geojsonHeadScanner';

export type { DetectedMappings, PropertyInfo } from './geojsonDetect';

/** Why a file cannot be previewed; the wizard words it in the console language. */
export type PreviewProblem =
  | { code: 'not_object' }
  | { code: 'no_features' }
  | { code: 'not_feature_collection'; found: string }
  | { code: 'no_complete_feature' }
  | { code: 'empty' }
  | { code: 'invalid_json'; detail: string };

export type GeoJsonPreview = {
  problem: PreviewProblem | null;
  featureCount: number;
  isPartial: boolean;
  properties: PropertyInfo[];
  detected: DetectedMappings;
  geometryTypes: string[];
  samples: { properties: Record<string, unknown>; geometryType: string | null }[];
};

type Feature = { properties?: Record<string, unknown> | null; geometry?: { type?: string } | null };

export const MAX_SAMPLES = 10;
const MAX_SAMPLE_VALUE_LENGTH = 100;
/** The most of a file the preview ever reads. */
export const PREVIEW_HEAD_BYTES = 8 * 1024 * 1024;
const BASE64_PREFIXES = ['/9j/', 'iVBOR', 'R0lGO', 'UklGR', 'Qk'];

function failed(problem: PreviewProblem): GeoJsonPreview {
  return {
    problem,
    featureCount: 0,
    isPartial: false,
    properties: [],
    detected: NO_DETECTION,
    geometryTypes: [],
    samples: [],
  };
}

export async function previewGeoJson(file: Blob): Promise<GeoJsonPreview> {
  try {
    const text = await file.slice(0, PREVIEW_HEAD_BYTES).text();
    return fromScan(text, file.size > PREVIEW_HEAD_BYTES);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    return failed({ code: 'invalid_json', detail });
  }
}

function fromScan(text: string, isPartial: boolean): GeoJsonPreview {
  const scan = scanGeoJsonHead(text, MAX_SAMPLES);
  if (scan.error) return failed({ code: 'not_object' });
  if (scan.rootType !== null && scan.rootType !== 'FeatureCollection') {
    return failed({ code: 'not_feature_collection', found: scan.rootType });
  }
  if (!scan.featuresFound) return failed({ code: 'no_features' });
  if (scan.completeFeatureCount === 0) {
    return failed({ code: isPartial ? 'no_complete_feature' : 'empty' });
  }
  const features = scan.sampleFeatures as Feature[];
  const properties = propertyList(features);
  const geometryTypes = [
    ...new Set(features.map((f) => f.geometry?.type).filter((t): t is string => Boolean(t))),
  ].sort();
  return {
    problem: null,
    featureCount: scan.completeFeatureCount,
    isPartial,
    properties,
    detected: detectPropertyMappings(properties),
    geometryTypes,
    samples: features.map((f) => ({
      properties: f.properties ?? {},
      geometryType: f.geometry?.type ?? null,
    })),
  };
}

function typeOf(value: unknown): ValueType {
  if (value === null || value === undefined) return 'null';
  if (Array.isArray(value)) return 'array';
  const type = typeof value;
  return type === 'string' || type === 'number' || type === 'boolean' ? type : 'object';
}

const PRIORITY: ValueType[] = ['string', 'number', 'boolean', 'object', 'array'];

function sampleText(value: unknown): string {
  if (value === null || value === undefined) return '';
  const text = typeof value === 'object' ? JSON.stringify(value) : String(value);
  return text.length > MAX_SAMPLE_VALUE_LENGTH
    ? `${text.slice(0, MAX_SAMPLE_VALUE_LENGTH)}...`
    : text;
}

function isBase64Image(value: unknown): boolean {
  if (typeof value !== 'string' || value.length < 20) return false;
  return value.startsWith('data:image/') || BASE64_PREFIXES.some((p) => value.startsWith(p));
}

function propertyList(features: Feature[]): PropertyInfo[] {
  const stats = new Map<string, { values: unknown[]; types: Set<ValueType>; count: number }>();
  for (const feature of features) {
    for (const [name, value] of Object.entries(feature.properties ?? {})) {
      const stat = stats.get(name) ?? { values: [], types: new Set(), count: 0 };
      stats.set(name, stat);
      stat.count++;
      stat.types.add(typeOf(value));
      if (stat.values.length < 3 && value !== null && value !== undefined) stat.values.push(value);
    }
  }
  const out: PropertyInfo[] = [...stats].map(([name, s]) => ({
    name,
    sampleValue: sampleText(s.values[0]),
    valueType: PRIORITY.find((t) => s.types.has(t)) ?? 'null',
    occurrences: s.count,
    isUrl: s.values.some((v) => typeof v === 'string' && /^https?:\/\//.test(v)),
    isNumeric:
      s.types.has('number') ||
      s.values.some((v) => typeof v === 'string' && !Number.isNaN(Number(v))),
    isBase64Image: s.values.some(isBase64Image),
  }));
  return out.sort((a, b) => b.occurrences - a.occurrences || a.name.localeCompare(b.name));
}
