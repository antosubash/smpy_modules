import { useEffect, useState } from 'react';
import { errorText, listCalendars } from '../utils/api';
import type { Calendar } from '../utils/types';

export function useCalendars() {
  const [request, setRequest] = useState({ trashed: false });
  const { trashed } = request;
  const [loaded, setLoaded] = useState<{ trashed: boolean; items: Calendar[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    setLoading(true);
    setError(null);
    const { trashed } = request;
    listCalendars(trashed)
      .then((items) => {
        if (current) setLoaded({ trashed, items });
      })
      .catch((e) => {
        if (current) setError(errorText(e));
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [request]);
  return {
    items: loaded?.trashed === trashed ? loaded.items : [],
    loading,
    error,
    trashed,
    setTrashed: (trashed: boolean) => setRequest({ trashed }),
    reload: () => setRequest((current) => ({ ...current })),
  };
}
