import { describe, expect, it } from 'vitest';

import { PREVIEW_HEAD_BYTES, previewGeoJson } from './geojsonPreview';

const collection = (features: unknown[], extra = '') =>
  `{"type":"FeatureCollection"${extra},"features":${JSON.stringify(features)}}`;
const point = (properties: Record<string, unknown> | null) => ({
  type: 'Feature',
  properties,
  geometry: { type: 'Point', coordinates: [8.5, 47.3] },
});
const blob = (text: string) => new Blob([text]);

describe('previewGeoJson', () => {
  it('counts a small file exactly and maps URL, coordinates, time and id', async () => {
    const preview = await previewGeoJson(
      blob(
        collection([
          point({ image_url: 'https://x.test/a.jpg', lat: 47.3, lng: '8.5', date: 'd', id: 7 }),
          point({ image_url: 'https://x.test/b.jpg', lat: 47.4, lng: '8.6', date: 'd', id: 8 }),
        ]),
      ),
    );
    expect(preview.problem).toBeNull();
    expect(preview.featureCount).toBe(2);
    expect(preview.isPartial).toBe(false);
    expect(preview.geometryTypes).toEqual(['Point']);
    expect(preview.detected).toEqual({
      url_prop: 'image_url',
      image_prop: null,
      lat_prop: 'lat',
      lng_prop: 'lng',
      datetime_prop: 'date',
      external_id_prop: 'id',
    });
  });

  it('detects an embedded base64 image by its bytes, whatever the property is called', async () => {
    const jpeg = `/9j/${'A'.repeat(40)}`;
    const preview = await previewGeoJson(blob(collection([point({ pic: jpeg, site: 'P1' })])));
    expect(preview.detected.image_prop).toBe('pic');
    expect(preview.detected.url_prop).toBeNull();
  });

  it('does not offer an embedded image under the conventional name "image" as an address', async () => {
    const jpeg = `/9j/${'A'.repeat(40)}`;
    const preview = await previewGeoJson(blob(collection([point({ image: jpeg })])));
    expect(preview.detected.image_prop).toBe('image');
    expect(preview.detected.url_prop).toBeNull();
  });

  it('samples at most ten features but counts them all', async () => {
    const features = Array.from({ length: 25 }, (_, i) => point({ id: i }));
    const preview = await previewGeoJson(blob(collection(features)));
    expect(preview.featureCount).toBe(25);
    expect(preview.samples).toHaveLength(10);
  });

  it('reads only a bounded head of a large file and calls its count a lower bound', async () => {
    const feature = JSON.stringify(
      point({ image_url: 'https://x.test/a.jpg', pad: 'x'.repeat(1000) }),
    );
    const head = `{"type":"FeatureCollection","features":[${feature},${feature},${feature}`;
    const tail = 'y'.repeat(PREVIEW_HEAD_BYTES);
    let read = 0;
    const file = new Blob([head, ',', tail]);
    const spy = {
      size: file.size,
      slice(start: number, end: number) {
        read = end - start;
        return file.slice(start, end);
      },
    } as unknown as Blob;
    const preview = await previewGeoJson(spy);
    expect(read).toBe(PREVIEW_HEAD_BYTES);
    expect(preview.problem).toBeNull();
    expect(preview.isPartial).toBe(true);
    expect(preview.featureCount).toBe(3);
    expect(preview.detected.url_prop).toBe('image_url');
  });

  it('names what is wrong with a file that is not a FeatureCollection', async () => {
    expect((await previewGeoJson(blob('[1,2]'))).problem).toEqual({ code: 'not_object' });
    expect((await previewGeoJson(blob('{"type":"Point","coordinates":[1,2]}'))).problem).toEqual({
      code: 'not_feature_collection',
      found: 'Point',
    });
    expect((await previewGeoJson(blob('{"type":"FeatureCollection"}'))).problem).toEqual({
      code: 'no_features',
    });
    expect((await previewGeoJson(blob(collection([])))).problem).toEqual({ code: 'empty' });
  });

  it('tolerates a feature with null properties', async () => {
    const preview = await previewGeoJson(
      blob(collection([point(null), point({ url: 'http://a/b' })])),
    );
    expect(preview.problem).toBeNull();
    expect(preview.detected.url_prop).toBe('url');
  });
});
