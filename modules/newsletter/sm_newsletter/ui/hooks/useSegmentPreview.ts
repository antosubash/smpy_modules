/**
 * The live "about N subscribers match" of a segment being edited.
 *
 * Debounced (`COUNT_DEBOUNCE_MS`); only complete rules are sent, so a half-filled row
 * never reaches the server. A superseded request is aborted and its answer ignored.
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { api, errorMessage } from '../utils/api';
import { useT } from '../utils/i18n';
import { ruleComplete } from '../utils/rules';
import type { Rule } from '../utils/types';
import { COUNT_DEBOUNCE_MS } from './useAudienceCount';

export function useSegmentPreview(listKey: string, rules: Rule[]) {
  const { t } = useT();
  const tRef = useRef(t);
  tRef.current = t;
  const [state, setState] = useState<{ count: number | null; error: string | null }>({
    count: null,
    error: null,
  });
  const body = useMemo(() => JSON.stringify(rules.filter(ruleComplete)), [rules]);

  useEffect(() => {
    const abort = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const { count } = await api.previewSegment(
          { list_type_key: listKey, rules: JSON.parse(body) as Rule[] },
          abort.signal,
        );
        if (!abort.signal.aborted) setState({ count, error: null });
      } catch (e) {
        if (!abort.signal.aborted) setState({ count: null, error: errorMessage(e, tRef.current) });
      }
    }, COUNT_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [listKey, body]);

  return state;
}
