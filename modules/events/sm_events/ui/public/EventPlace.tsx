import { keys, useT } from '../utils/i18n';
import type { Place } from './types';

const map = (p: Place) =>
  `https://www.openstreetmap.org/?mlat=${p.latitude}&mlon=${p.longitude}#map=16/${p.latitude}/${p.longitude}`;

/** Where: the venue and address (in person), the join link (online), or both (hybrid). */
export function EventPlace({ place }: { place: Place }) {
  const { t } = useT();
  const copy = keys.events.public.event;
  const physical = place.mode !== 'online' && (place.venue_name || place.address);
  const hasMap = place.latitude !== null && place.longitude !== null;
  if (!physical && !place.online_url && !hasMap) return null;
  return (
    <section aria-labelledby="place-title" className="space-y-1">
      <h2 id="place-title" className="font-semibold">
        {t(copy.place)}
      </h2>
      {place.mode === 'online' || place.mode === 'hybrid' ? (
        <p className="text-sm text-muted-foreground">
          {t(place.mode === 'online' ? copy.online : copy.hybrid)}
        </p>
      ) : null}
      {physical ? (
        <p>
          {place.venue_name ? <strong>{place.venue_name}</strong> : null}
          {place.venue_name && place.address ? <br /> : null}
          {place.address}
        </p>
      ) : null}
      {hasMap ? (
        <p>
          <a href={map(place)} rel="noopener nofollow" className="underline">
            {t(copy.map)}
          </a>
        </p>
      ) : null}
      {place.online_url ? (
        <p>
          <a href={place.online_url} rel="noopener nofollow" className="underline">
            {t(copy.join_online)}
          </a>
        </p>
      ) : null}
    </section>
  );
}
