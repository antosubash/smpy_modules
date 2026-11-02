/**
 * Partial reader for the start ("head") of a large GeoJSON FeatureCollection.
 *
 * Large files are previewed from a bounded slice instead of being read and
 * JSON.parse'd whole on the main thread. A slice usually ends mid-feature, so
 * it is not valid JSON; this scanner walks the top-level object by hand,
 * skipping values it does not need, and parses only complete features inside
 * the "features" array. Truncation is never an error: scanning simply stops
 * where the head ends.
 */

export interface GeoJsonHeadScan {
  /** Top-level "type" value, if it appeared within the head. */
  rootType: string | null;
  /** Whether the "features" array started within the head. */
  featuresFound: boolean;
  /** The first complete features, parsed (at most maxSamples). */
  sampleFeatures: unknown[];
  /** Number of complete features found within the head. */
  completeFeatureCount: number;
  /** Structural problem found before the head ended, if any. */
  error: string | null;
}

const WHITESPACE = new Set([' ', '\n', '\r', '\t']);
const BYTE_ORDER_MARK = 0xfeff;

function skipWhitespace(text: string, start: number): number {
  let index = start;
  while (index < text.length && WHITESPACE.has(text[index])) {
    index++;
  }
  return index;
}

/** Index just past the closing quote of the string at `start`, or -1 if the head ends first. */
function endOfString(text: string, start: number): number {
  let index = start + 1;
  while (index < text.length) {
    const char = text[index];
    if (char === '\\') {
      index += 2;
      continue;
    }
    if (char === '"') {
      return index + 1;
    }
    index++;
  }
  return -1;
}

/** Index just past the object/array opening at `start`, or -1 if the head ends first. */
function endOfContainer(text: string, start: number): number {
  let depth = 0;
  let index = start;
  while (index < text.length) {
    const char = text[index];
    if (char === '"') {
      const stringEnd = endOfString(text, index);
      if (stringEnd === -1) return -1;
      index = stringEnd;
      continue;
    }
    if (char === '{' || char === '[') {
      depth++;
    } else if (char === '}' || char === ']') {
      depth--;
      if (depth === 0) return index + 1;
    }
    index++;
  }
  return -1;
}

/** Index just past a number / true / false / null at `start`, or -1 if the head ends first. */
function endOfScalar(text: string, start: number): number {
  let index = start;
  while (index < text.length) {
    const char = text[index];
    if (char === ',' || char === '}' || char === ']' || WHITESPACE.has(char)) {
      return index;
    }
    index++;
  }
  return -1;
}

function endOfValue(text: string, start: number): number {
  const char = text[start];
  if (char === undefined) return -1;
  if (char === '"') return endOfString(text, start);
  if (char === '{' || char === '[') return endOfContainer(text, start);
  return endOfScalar(text, start);
}

/**
 * Walk the features array opening at `start`, parsing the first `maxSamples`
 * complete features and counting the rest. Returns the index just past the
 * array, or -1 if the head ends inside it.
 */
function scanFeaturesArray(
  text: string,
  start: number,
  maxSamples: number,
  scan: GeoJsonHeadScan,
): number {
  let index = start + 1;
  while (index < text.length) {
    index = skipWhitespace(text, index);
    const char = text[index];
    if (char === undefined) return -1;
    if (char === ']') return index + 1;
    if (char === ',') {
      index++;
      continue;
    }
    const featureEnd = endOfValue(text, index);
    if (featureEnd === -1) return -1;
    if (scan.sampleFeatures.length < maxSamples) {
      scan.sampleFeatures.push(JSON.parse(text.slice(index, featureEnd)));
    }
    scan.completeFeatureCount++;
    index = featureEnd;
  }
  return -1;
}

/**
 * Scan the head of a GeoJSON file. Throws SyntaxError only when a value that
 * is complete within the head is not valid JSON.
 */
export function scanGeoJsonHead(text: string, maxSamples: number): GeoJsonHeadScan {
  const scan: GeoJsonHeadScan = {
    rootType: null,
    featuresFound: false,
    sampleFeatures: [],
    completeFeatureCount: 0,
    error: null,
  };

  const firstIndex = text.charCodeAt(0) === BYTE_ORDER_MARK ? 1 : 0;
  let index = skipWhitespace(text, firstIndex);
  if (text[index] !== '{') {
    scan.error = 'File does not start with a JSON object';
    return scan;
  }
  index++;

  while (index < text.length) {
    index = skipWhitespace(text, index);
    const char = text[index];
    if (char === undefined || char === '}') break;
    if (char === ',') {
      index++;
      continue;
    }
    if (char !== '"') {
      scan.error = `Unexpected character "${char}" in the top-level object`;
      break;
    }

    const keyEnd = endOfString(text, index);
    if (keyEnd === -1) break;
    const key = JSON.parse(text.slice(index, keyEnd)) as string;
    index = skipWhitespace(text, keyEnd);
    if (index >= text.length) break;
    if (text[index] !== ':') {
      scan.error = `Expected ":" after the "${key}" key`;
      break;
    }
    index = skipWhitespace(text, index + 1);
    if (index >= text.length) break;

    if (key === 'features') {
      if (text[index] !== '[') {
        scan.error = "Missing 'features' array in GeoJSON";
        break;
      }
      scan.featuresFound = true;
      const featuresEnd = scanFeaturesArray(text, index, maxSamples, scan);
      if (featuresEnd === -1) break;
      index = featuresEnd;
      continue;
    }

    const valueEnd = endOfValue(text, index);
    if (valueEnd === -1) break;
    if (key === 'type') {
      const typeValue: unknown = JSON.parse(text.slice(index, valueEnd));
      scan.rootType = typeof typeValue === 'string' ? typeValue : null;
    }
    index = valueEnd;
  }

  return scan;
}
