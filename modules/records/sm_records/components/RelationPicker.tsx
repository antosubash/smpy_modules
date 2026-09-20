import { useT } from '@simple-module-py/i18n';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { ApiError, getRecord } from '../utils/api';
import { searchByTitle } from '../utils/relation-search';
import type { ExpandedRef, FieldDef, RecordRead } from '../utils/types';
import {
  isRelationValue,
  type RelationValue,
  relationIsMany,
  relationTarget,
} from '../utils/values';

/** Long enough that typing a word is one request, short enough that the list
 *  feels attached to the keyboard. */
const DEBOUNCE_MS = 250;

/** `title: null` means "looked up and not there" — a dangling reference,
 *  which a soft-deleted target legitimately produces (design §9). `restricted`
 *  marks a target this caller may not view: `title` is `null` there too, but
 *  it renders as a different, non-alarming chip — nothing here failed, the
 *  caller just isn't allowed to see it. */
type LabelEntry = { title: string | null; restricted: boolean };
type LabelMap = Record<string, LabelEntry>;

/** `expanded` keyed by `uuid` rather than trusted to line up positionally
 *  with `selected`: the caller may have picked a new value since the page's
 *  own `?expand=` was resolved, and a uuid the map does not know is exactly
 *  the signal to fall back to this component's own lookup below. */
function expandedByUuid(expanded: ExpandedRef[] | undefined): Record<string, ExpandedRef> {
  const map: Record<string, ExpandedRef> = {};
  for (const ref of expanded ?? []) map[ref.uuid] = ref;
  return map;
}

function valuesOf(value: unknown, many: boolean): RelationValue[] {
  if (many) return Array.isArray(value) ? value.filter(isRelationValue) : [];
  return isRelationValue(value) ? [value] : [];
}

/**
 * Picks the target of a `relation` field: `{type, uuid}`, or a list of them
 * when `options.many`.
 */
export function RelationPicker({
  field,
  value,
  onChange,
  disabled,
  expanded,
}: {
  field: FieldDef;
  value: unknown;
  onChange: (next: unknown) => void;
  disabled?: boolean;
  /** This field's slice of the record's `expanded` (design §9), when the
   *  page already resolved it — the editor's own load always does. Consulted
   *  before falling back to this component's per-uuid lookup, so a value the
   *  page expanded is never fetched twice. */
  expanded?: ExpandedRef[];
}) {
  const { t } = useT();
  const target = relationTarget(field);
  const many = relationIsMany(field);
  const selected = useMemo(() => valuesOf(value, many), [value, many]);
  const expandedMap = useMemo(() => expandedByUuid(expanded), [expanded]);

  const [labels, setLabels] = useState<LabelMap>({});
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<RecordRead[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const labelsRef = useRef<LabelMap>({});
  labelsRef.current = labels;

  // Resolve the display title of whatever is already selected: from the
  // page's own `expanded` first (no request at all), and only fetched here
  // for a uuid it does not cover — a value picked this session, or a record
  // whose page never expanded it. A 404 is an expected answer either way,
  // not a failure: it marks the chip and moves on.
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

  useEffect(() => {
    const term = query.trim();
    if (!target || term === '') {
      setResults([]);
      setSearchError(null);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const timer = setTimeout(() => {
      searchByTitle(target, term)
        .then((items) => {
          if (cancelled) return;
          setResults(items);
          setSearchError(null);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setResults([]);
          setSearchError(err instanceof Error ? err.message : String(err));
        })
        .finally(() => {
          if (!cancelled) setSearching(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, target]);

  const pick = useCallback(
    (record: RecordRead) => {
      setLabels((prev) => ({
        ...prev,
        [record.uuid]: { title: record.display_title, restricted: false },
      }));
      const ref: RelationValue = { type: target, uuid: record.uuid };
      if (!many) {
        onChange(ref);
      } else if (!selected.some((item) => item.uuid === record.uuid)) {
        onChange([...selected, ref]);
      }
      setQuery('');
      setResults([]);
    },
    [many, onChange, selected, target],
  );

  const remove = useCallback(
    (uuid: string) => {
      onChange(many ? selected.filter((item) => item.uuid !== uuid) : null);
    },
    [many, onChange, selected],
  );

  const missingLabel = t('records.relation.missing', { defaultValue: 'Missing record' });
  const restrictedLabel = t('records.relation.restricted', { defaultValue: 'Restricted' });
  const removeLabel = t('records.relation.remove', { defaultValue: 'Remove' });

  return (
    <div className="grid gap-2" data-testid={`records-relation-${field.key}`}>
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {selected.map((ref) => {
            const entry = labels[ref.uuid];
            const restricted = entry?.restricted ?? false;
            const gone = entry !== undefined && !restricted && entry.title === null;
            const chipText = restricted
              ? restrictedLabel
              : gone
                ? missingLabel
                : (entry?.title ?? ref.uuid);
            return (
              <Badge
                key={ref.uuid}
                variant={gone ? 'destructive' : restricted ? 'outline' : 'secondary'}
                className={`gap-1 py-1 ${restricted ? 'text-muted-foreground' : ''}`}
                data-testid={restricted ? 'records-relation-chip-restricted' : undefined}
              >
                <span>{chipText}</span>
                <button
                  type="button"
                  disabled={disabled}
                  aria-label={removeLabel}
                  className="ml-1 opacity-70 hover:opacity-100 disabled:opacity-40"
                  onClick={() => remove(ref.uuid)}
                >
                  {REMOVE_GLYPH}
                </button>
              </Badge>
            );
          })}
        </div>
      )}

      {(many || selected.length === 0) && (
        <Input
          type="search"
          value={query}
          disabled={disabled || !target}
          placeholder={t('records.relation.search_placeholder', {
            defaultValue: 'Search by title…',
          })}
          aria-label={t('records.relation.search_label', { defaultValue: 'Search for a record' })}
          onChange={(event) => setQuery(event.target.value)}
        />
      )}

      {!target && (
        <p className="text-sm text-destructive">
          {t('records.relation.no_target', {
            defaultValue: 'This relation field has no target type configured.',
          })}
        </p>
      )}
      {searchError && <p className="text-sm text-destructive">{searchError}</p>}
      {query.trim() !== '' && (
        <div className="rounded-md border">
          {searching && results.length === 0 && (
            <p className="p-2 text-sm text-muted-foreground">
              {t('records.relation.searching', { defaultValue: 'Searching…' })}
            </p>
          )}
          {!searching && results.length === 0 && (
            <p className="p-2 text-sm text-muted-foreground">
              {t('records.relation.no_results', { defaultValue: 'No matching records' })}
            </p>
          )}
          {results.map((record) => (
            <Button
              key={record.uuid}
              type="button"
              variant="ghost"
              disabled={disabled}
              className="w-full justify-start rounded-none font-normal"
              onClick={() => pick(record)}
            >
              {record.display_title}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

/** A glyph, not copy — the accessible name is the translated `aria-label`. */
const REMOVE_GLYPH = '×';
