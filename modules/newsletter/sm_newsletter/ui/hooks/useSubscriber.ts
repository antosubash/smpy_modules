import { useCallback, useEffect, useRef, useState } from 'react';

import { api, errorMessage } from '../utils/api';
import { useT } from '../utils/i18n';
import type { SubscriberDetail } from '../utils/types';

/** One subscriber's detail (fields, engagement, suppressions); `null` uuid loads nothing. */
export function useSubscriber(listKey: string, uuid: string | null) {
  const { t } = useT();
  const tRef = useRef(t);
  tRef.current = t;
  const [detail, setDetail] = useState<SubscriberDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  // `version` is not read: bumping it is how `reload` re-runs this effect.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  useEffect(() => {
    let live = true;
    if (!uuid) {
      setDetail(null);
      return;
    }
    api
      .getSubscriber(listKey, uuid)
      .then((d) => {
        if (!live) return;
        setError(null);
        setDetail(d);
      })
      .catch((e) => live && setError(errorMessage(e, tRef.current)));
    return () => {
      live = false;
    };
  }, [listKey, uuid, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { detail, error, reload };
}
