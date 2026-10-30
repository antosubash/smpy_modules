/**
 * Auto-detection of the GeoJSON properties that feed an image's fields (image
 * URL or embedded image, latitude, longitude, capture time, external id) from
 * the sampled properties. Ported from the portal's `geojsonPropertyDetection`
 * and kept to what the server's `Mapping` takes; it only proposes, the person
 * decides.
 */

export type ValueType = 'string' | 'number' | 'boolean' | 'null' | 'object' | 'array';

export type PropertyInfo = {
  name: string;
  sampleValue: string;
  valueType: ValueType;
  occurrences: number;
  isUrl: boolean;
  isNumeric: boolean;
  isBase64Image: boolean;
};

/** The server's `Mapping` field names, so a detection is a mapping as it is. */
export type DetectedMappings = {
  url_prop: string | null;
  image_prop: string | null;
  lat_prop: string | null;
  lng_prop: string | null;
  datetime_prop: string | null;
  external_id_prop: string | null;
};

export const NO_DETECTION: DetectedMappings = {
  url_prop: null,
  image_prop: null,
  lat_prop: null,
  lng_prop: null,
  datetime_prop: null,
  external_id_prop: null,
};

const URL_NAMES = ['image_url', 'url', 'photo_url', 'image'];
const IMAGE_NAMES = [
  'image',
  'image_data',
  'base64',
  'photo',
  'photo_data',
  'image_base64',
  'data',
];
const DATETIME_NAMES = ['captured_at', 'date', 'timestamp', 'datetime', 'created_at'];
const LAT_NAMES = ['latitude', 'lat', 'y'];
const LNG_NAMES = ['longitude', 'lon', 'lng', 'x'];
const ID_NAMES = ['id', 'external_id', 'photo_id', 'image_id'];

/** The first of `names` (in priority order) that a property is called. */
function byName(
  properties: PropertyInfo[],
  names: string[],
  accept: (p: PropertyInfo) => boolean = () => true,
): string | null {
  for (const name of names) {
    const found = properties.find((p) => p.name.toLowerCase() === name && accept(p));
    if (found) return found.name;
  }
  return null;
}

export function detectPropertyMappings(properties: PropertyInfo[]): DetectedMappings {
  return {
    image_prop:
      properties.find((p) => p.isBase64Image)?.name ??
      byName(properties, IMAGE_NAMES, (p) => p.valueType === 'string'),
    url_prop:
      properties.find((p) => p.isUrl)?.name ??
      byName(properties, URL_NAMES, (p) => !p.isBase64Image),
    lat_prop: byName(properties, LAT_NAMES, (p) => p.isNumeric),
    lng_prop: byName(properties, LNG_NAMES, (p) => p.isNumeric),
    datetime_prop: byName(properties, DATETIME_NAMES),
    external_id_prop: byName(properties, ID_NAMES),
  };
}
