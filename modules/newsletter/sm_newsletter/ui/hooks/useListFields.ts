/** A list's segmentable fields (`GET /lists/{key}/fields`): loaded once per list. */

import { useEffect, useRef, useState } from 'react';

import { api, errorMessage } from '../utils/api';
import { useT } from '../utils/i18n';
import type { ListField } from '../utils/types';

export function useListFields(listKey: string) {
  const { t } = useT();
  const tRef = useRef(t);
  tRef.current = t;
  const [fields, setFields] = useState<ListField[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setFields(null);
    setError(null);
    // No list yet (the pages' first render, or a tenant without lists): `/lists//fields` is a 404.
    if (!listKey) return;
    api
      .listFields(listKey)
      .then((f) => live && setFields(f))
      .catch((e) => live && setError(errorMessage(e, tRef.current)));
    return () => {
      live = false;
    };
  }, [listKey]);

  return { fields, error };
}
