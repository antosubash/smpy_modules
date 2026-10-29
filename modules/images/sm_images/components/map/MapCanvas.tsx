import {
  addProtocol,
  type GeoJSONSource,
  type LngLatBoundsLike,
  Map as MapLibreMap,
  NavigationControl,
} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Protocol } from 'pmtiles';
import { useEffect, useRef, useState } from 'react';

import { keys, useT } from '../../utils/i18n';

import { boundsOf, type MapSource } from './mapSource';
import { installMapWorker } from './mapWorker';

/** The tippecanoe layer name (`-l images`), and the sources and layers we add. */
const TILE_LAYER = 'images';
const SOURCE = 'images';
const CLUSTERS = 'images-clusters';
const POINTS = 'images-points';

// A neutral, tile-server-free basemap: a flat background. The images are the
// content; there is no key to leak and no third-party request to make.
const STYLE = {
  version: 8 as const,
  sources: {},
  layers: [
    { id: 'background', type: 'background' as const, paint: { 'background-color': '#e7ecef' } },
  ],
};

let protocolAdded = false;
function ensureProtocol() {
  if (protocolAdded) return;
  installMapWorker();
  addProtocol('pmtiles', new Protocol().tile);
  protocolAdded = true;
}

type Props = {
  source: MapSource;
  bbox: number[] | null;
  label: string;
  onSelect: (imageId: string) => void;
};

function addLayers(map: MapLibreMap, source: MapSource) {
  const clustered = source.kind === 'points';
  if (source.kind === 'tiles') {
    map.addSource(SOURCE, { type: 'vector', url: `pmtiles://${source.url}` });
  } else {
    map.addSource(SOURCE, {
      type: 'geojson',
      cluster: true,
      clusterRadius: 40,
      clusterMaxZoom: 14,
      data: { type: 'FeatureCollection', features: source.features },
    });
  }
  const layer = clustered ? {} : { 'source-layer': TILE_LAYER };
  map.addLayer({
    id: CLUSTERS,
    type: 'circle',
    source: SOURCE,
    ...layer,
    filter: ['has', 'point_count'],
    paint: {
      'circle-color': '#2563eb',
      'circle-opacity': 0.8,
      'circle-radius': ['step', ['get', 'point_count'], 12, 10, 16, 100, 22, 1000, 30],
      'circle-stroke-width': 2,
      'circle-stroke-color': '#ffffff',
    },
  });
  map.addLayer({
    id: POINTS,
    type: 'circle',
    source: SOURCE,
    ...layer,
    filter: ['!', ['has', 'point_count']],
    paint: {
      'circle-color': '#dc2626',
      'circle-radius': 6,
      'circle-stroke-width': 2,
      'circle-stroke-color': '#ffffff',
    },
  });
}

/** MapLibre on a flat background, with the collection's points as clusters.
 *  A click on a point calls `onSelect(imageId)`; on a cluster it zooms in. */
export default function MapCanvas({ source, bbox, label, onSelect }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const select = useRef(onSelect);
  select.current = onSelect;
  const { t } = useT();
  const [failed, setFailed] = useState(false);

  // The map is built once per source; a re-render with the same source keeps it.
  // biome-ignore lint/correctness/useExhaustiveDependencies: bbox only seeds the first view
  useEffect(() => {
    if (!host.current) return;
    ensureProtocol();
    const map = new MapLibreMap({
      container: host.current,
      style: STYLE,
      center: [0, 20],
      zoom: 1,
      attributionControl: false,
    });
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    setFailed(false);
    // A worker that never starts, a tile or archive that does not load: say so.
    map.on('error', () => setFailed(true));
    map.on('load', () => {
      addLayers(map, source);
      const bounds = boundsOf(bbox);
      if (bounds) {
        map.fitBounds(bounds as LngLatBoundsLike, { padding: 40, maxZoom: 14, animate: false });
      }
      host.current?.setAttribute('data-map-ready', source.kind);
    });
    // How many of our features are drawn right now: 0 means the worker or the
    // data did not make it, whatever the canvas shows.
    map.on('idle', () => {
      const drawn = map.getLayer(POINTS)
        ? map.queryRenderedFeatures({ layers: [CLUSTERS, POINTS] })
        : [];
      host.current?.setAttribute('data-map-features', String(drawn.length));
    });
    map.on('click', POINTS, (event) => {
      const id = event.features?.[0]?.properties?.id;
      if (typeof id === 'string') select.current(id);
    });
    map.on('click', CLUSTERS, async (event) => {
      const feature = event.features?.[0];
      if (feature?.geometry.type !== 'Point') return;
      const center = feature.geometry.coordinates as [number, number];
      let zoom = map.getZoom() + 2;
      if (source.kind === 'points') {
        const clusterId = feature.properties?.cluster_id;
        const geojson = map.getSource(SOURCE) as GeoJSONSource;
        zoom = await geojson.getClusterExpansionZoom(clusterId).catch(() => zoom);
      }
      map.easeTo({ center, zoom });
    });
    for (const layer of [POINTS, CLUSTERS]) {
      map.on('mouseenter', layer, () => map.getCanvas().style.setProperty('cursor', 'pointer'));
      map.on('mouseleave', layer, () => map.getCanvas().style.removeProperty('cursor'));
    }
    return () => map.remove();
  }, [source]);

  return (
    <>
      <div
        ref={host}
        role="img"
        aria-label={label}
        className="h-[60vh] min-h-80 w-full overflow-hidden rounded-md border"
        data-testid="images-map"
      />
      {failed && (
        <p className="mt-2 text-sm text-destructive" role="alert" data-testid="images-map-error">
          {t(keys.images.map.failed)}
        </p>
      )}
    </>
  );
}
