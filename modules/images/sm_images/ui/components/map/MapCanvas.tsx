import {
  AttributionControl,
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

import { boundsOf, type MapSource, pointsBounds } from './mapSource';
import { installMapWorker } from './mapWorker';

/** The tippecanoe layer name (`-l images`), and the sources and layers we add. */
const TILE_LAYER = 'images';
const SOURCE = 'images';
const CLUSTERS = 'images-clusters';
const POINTS = 'images-points';
/** Room around the fitted points; more on the top right, where the zoom control sits. */
const FIT_PADDING = { top: 56, right: 64, bottom: 40, left: 40 };

// The flat, tile-server-free background: drawn when no basemap is configured
// (`map_style_url` empty, no third-party request at all) and when the configured
// one cannot be fetched - the points matter more than the streets under them.
const FLAT = {
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
  /** The basemap's MapLibre style URL; empty draws the flat background. */
  styleUrl?: string;
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

/** Whether an error event came from a tile or source rather than the style. */
function fromTile(event: unknown): boolean {
  const e = event as { tile?: unknown; sourceId?: unknown } | undefined;
  return Boolean(e?.tile || e?.sourceId);
}

/** MapLibre on the configured basemap (or a flat background), with the
 *  collection's points as clusters on top of it. A click on a point calls
 *  `onSelect(imageId)`; on a cluster it zooms in. */
export default function MapCanvas({ source, styleUrl = '', bbox, label, onSelect }: Props) {
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
      style: styleUrl || FLAT,
      center: [0, 20],
      zoom: 1,
      // The basemap's own credits (OpenStreetMap's, for the default), folded
      // into an (i) button so they do not cover the points.
      attributionControl: false,
    });
    map.addControl(new AttributionControl({ compact: true }), 'bottom-right');
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    setFailed(false);
    // The basemap's style document arrived (its tiles may still fail, harmlessly).
    let styled = false;
    let basemap = Boolean(styleUrl);
    map.on('styledata', () => {
      styled = true;
    });
    // Only an error before the first `load` (the style, the worker) means the
    // map failed; one after it, or a basemap tile's at any time, is logged.
    // A basemap whose style cannot be fetched (offline, blocked, gone) gives
    // way to the flat background once, and the points are drawn on that.
    let loaded = false;
    map.on('error', (event) => {
      if (loaded || fromTile(event)) {
        console.warn('images map error', event?.error ?? event);
      } else if (basemap && !styled) {
        basemap = false;
        console.warn('images basemap unavailable', event?.error ?? event);
        map.setStyle(FLAT, { diff: false });
      } else {
        setFailed(true);
      }
    });
    map.on('load', () => {
      loaded = true;
      setFailed(false);
      // Added after the style loaded and with no `beforeId`: above every
      // basemap layer, labels included.
      addLayers(map, source);
      // Points drawn from GeoJSON are fitted themselves: `bbox` comes from the
      // page props, which may predate the points an upload just located.
      const bounds = (source.kind === 'points' && pointsBounds(source.features)) || boundsOf(bbox);
      if (bounds) {
        const fit = { padding: FIT_PADDING, maxZoom: 14, animate: false };
        map.fitBounds(bounds as LngLatBoundsLike, fit);
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
  }, [source, styleUrl]);

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
