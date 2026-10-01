import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { ApiError } from '../utils/api';
import { getRecord } from '../utils/api-records';
import type { ExpandedRef, RecordRead } from '../utils/types';
import type { RelationValue } from '../utils/values';

/** `title: null` means "looked up and not there" — a dangling reference,
 *  which a soft-deleted target legitimately produces (design §9). `restricted`
 *  marks a target this caller may not view: `title` is `null` there too, but
 *  it renders as a different, non-alarming chip — nothing here failed, the
 *  caller just isn't allowed to see it. */
export type LabelEntry = { title: string | null; restricted: boolean };
export type LabelMap = Record<string, LabelEntry>;

/** `expanded` keyed by `uuid` rather than trusted to line up positionally
 *  with `selected`: the caller may have picked a new value since the page's
 *  own `?expand=` was resolved, and a uuid the map does not know is exactly
 *  the signal to fall back to this hook's own lookup below. */
function expandedByUuid(expanded: ExpandedRef[] | undefined): Record<string, ExpandedRef> {
  const map: Record<string, ExpandedRef> = {};
  for (const ref of expanded ?? []) map[ref.uuid] = ref;
  return map;
}

/**
 * Display titles for whatever a relation field already holds.
 *
 * Its own hook rather than an effect inside `RelationPicker`: that component
 * grew the WAI-ARIA combobox keyboard handling (UX review R20) and ran past
 * the 300-line cap, and "how a uuid becomes a name" is a self-contained
 * question — resolved from the page's own `expanded` first (no request at
 * all), and only fetched for a uuid it does not cover: a value picked this
 * session, or a record whose page never expanded it. A 404 is an expected
 * answer either way, not a failure: it marks the chip and moves on.
 */
export function useRelationLabels(
  target: string,
  selected: RelationValue[],
  expanded: ExpandedRef[] | undefined,
): { labels: LabelMap; remember: (record: RecordRead) => void } {
  const expandedMap = useMemo(() => expandedByUuid(expanded), [expanded]);
  const [labels, setLabels] = useState<LabelMap>({});
  const labelsRef = useRef<LabelMap>({});
  labelsRef.current = labels;

  useEffect(() => {
    if (!target) return;
    let cancelled = false;
    const seeded: [string, LabelEntry][] = [];
    const missing: string[] = [];
    for (const ref of selected) {
      if (ref.uuid in labelsRef.current) continue;
      const exp = expandedMap[ref.uuid];
      if (!exp) {
        missing.push(ref.uuid);
      } else if (exp.restricted) {
        seeded.push([ref.uuid, { title: null, restricted: true }]);
      } else {
        seeded.push([
          ref.uuid,
          { title: exp.dangling ? null : exp.display_title, restricted: false },
        ]);
      }
    }
    if (seeded.length > 0) setLabels((prev) => ({ ...prev, ...Object.fromEntries(seeded) }));
    if (missing.length === 0) return;
    void Promise.all(
      missing.map(async (uuid): Promise<readonly [string, LabelEntry] | null> => {
        try {
          const record = await getRecord(target, uuid);
          return [uuid, { title: record.display_title, restricted: false }] as const;
        } catch (err) {
          // A 404 is a *fact* about the reference and is cached as one. Any
          // other failure is about the network, so nothing is cached and the
          // chip keeps showing the raw uuid until a later render retries.
          if (err instanceof ApiError && err.status === 404) {
            return [uuid, { title: null, restricted: false }] as const;
          }
          return null;
        }
      }),
    ).then((pairs) => {
      if (cancelled) return;
      const resolved = pairs.filter((pair): pair is readonly [string, LabelEntry] => pair !== null);
      if (resolved.length > 0) setLabels((prev) => ({ ...prev, ...Object.fromEntries(resolved) }));
    });
    return () => {
      cancelled = true;
    };
  }, [target, selected, expandedMap]);

  /** A record picked from the results is already named — remember it so the
   *  chip renders straight away rather than after a round trip for a title
   *  this component was just handed. */
  const remember = useCallback((record: RecordRead) => {
    setLabels((prev) => ({
      ...prev,
      [record.uuid]: { title: record.display_title, restricted: false },
    }));
  }, []);

  return { labels, remember };
}
