/**
 * The live "about N subscribers match" of a segment being edited.
 *
 * Debounced (`COUNT_DEBOUNCE_MS`); only complete rules are sent, so a half-filled row
 * never reaches the server. A superseded request is aborted and its answer ignored.
 * Nothing is asked while `enabled` is false (the editor is closed), and the answer is
 * cleared when it turns on again or the list changes, so an old count never shows.
 * A 422 naming `rules[i]` of the sent (complete-only) rules is mapped back to the row.
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { api, errorMessage } from '../utils/api';
import { useT } from '../utils/i18n';
import { invalidRuleIndex, ruleComplete } from '../utils/rules';
import type { Rule } from '../utils/types';
import { COUNT_DEBOUNCE_MS } from './useAudienceCount';

interface State {
  count: number | null;
  error: string | null;
  /** Index into the complete rules that were sent. */
  sentBad: number | null;
}
const EMPTY: State = { count: null, error: null, sentBad: null };

export function useSegmentPreview(listKey: string, rules: Rule[], enabled = true) {
  const { t } = useT();
  const tRef = useRef(t);
  tRef.current = t;
  const [state, setState] = useState<State>(EMPTY);
  const sent = useMemo(() => rules.flatMap((r, i) => (ruleComplete(r) ? [i] : [])), [rules]);
  const body = useMemo(() => JSON.stringify(sent.map((i) => rules[i])), [rules, sent]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset on (re)open and list switch
  useEffect(() => {
    setState(EMPTY);
  }, [enabled, listKey]);

  useEffect(() => {
    if (!enabled) return;
    const abort = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const { count } = await api.previewSegment(
          { list_type_key: listKey, rules: JSON.parse(body) as Rule[] },
          abort.signal,
        );
        if (!abort.signal.aborted) setState({ count, error: null, sentBad: null });
      } catch (e) {
        if (!abort.signal.aborted) {
          setState({
            count: null,
            error: errorMessage(e, tRef.current),
            sentBad: invalidRuleIndex(e),
          });
        }
      }
    }, COUNT_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [enabled, listKey, body]);

  const badRow = state.sentBad === null ? null : (sent[state.sentBad] ?? null);
  return { count: state.count, error: state.error, badRow };
}
