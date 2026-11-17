import { useCallback, useEffect, useRef, useState } from 'react';
import { errorText, listCategories } from '../utils/api';
import type { Category } from '../utils/types';

export function useCategories() {
  const [items, setItems] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const reload = useCallback(() => {
    const mine = ++generation.current;
    setLoading(true);
    setError(null);
    listCategories()
      .then((rows) => {
        if (mine === generation.current) setItems(rows);
      })
      .catch((e) => {
        if (mine === generation.current) setError(errorText(e));
      })
      .finally(() => {
        if (mine === generation.current) setLoading(false);
      });
  }, []);
  useEffect(() => {
    reload();
    return () => {
      ++generation.current;
    };
  }, [reload]);
  return { items, loading, error, reload };
}
