import { lazy, Suspense, useEffect, useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import { type MapSource, resolveMapSource } from './mapSource';

// The map library (MapLibre, PMTiles, their CSS) is a chunk of its own: only a
// screen that shows a map downloads it.
const MapCanvas = lazy(() => import('./MapCanvas'));

type Props = {
  /** `…/points` and `…/map.pmtiles` of the collection, admin or anonymous. */
  pointsUrl: string;
  mapUrl: string;
  /** The basemap's MapLibre style URL (`map_style_url`); empty is a flat background. */
  styleUrl?: string;
  bbox: number[] | null;
  onSelect: (imageId: string) => void;
};

type State = { phase: 'loading' } | { phase: 'failed' } | { phase: 'ready'; source: MapSource };

/** A collection's map: finds out whether an archive exists, falls back to the
 *  points, and says so when there is nothing to place. */
export function CollectionMap({ pointsUrl, mapUrl, styleUrl = '', bbox, onSelect }: Props) {
  const { t } = useT();
  const [state, setState] = useState<State>({ phase: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    setState({ phase: 'loading' });
    resolveMapSource({ pointsUrl, mapUrl }, controller.signal)
      .then((source) => setState({ phase: 'ready', source }))
      .catch(() => {
        if (!controller.signal.aborted) setState({ phase: 'failed' });
      });
    return () => controller.abort();
  }, [pointsUrl, mapUrl]);

  if (state.phase === 'loading') {
    return <p className="text-sm text-muted-foreground">{t(keys.images.map.loading)}</p>;
  }
  if (state.phase === 'failed') {
    return (
      <p className="text-sm text-destructive" role="alert">
        {t(keys.images.map.failed)}
      </p>
    );
  }
  if (state.source.kind === 'points' && state.source.features.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
        {t(keys.images.map.empty)}
      </div>
    );
  }
  return (
    <>
      {state.source.kind === 'points' && state.source.truncated && (
        <p className="mb-2 text-sm text-muted-foreground" data-testid="images-map-truncated">
          {t(keys.images.map.truncated, { count: state.source.features.length })}
        </p>
      )}
      <Suspense
        fallback={<p className="text-sm text-muted-foreground">{t(keys.images.map.loading)}</p>}
      >
        <MapCanvas
          source={state.source}
          styleUrl={styleUrl}
          bbox={bbox}
          label={t(keys.images.map.label)}
          onSelect={onSelect}
        />
      </Suspense>
    </>
  );
}
