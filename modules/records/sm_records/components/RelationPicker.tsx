import { useT } from '@simple-module-py/i18n';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { ApiError, buildFilterParam, getRecord, listRecords } from '../utils/api';
import type { FieldDef, RecordRead } from '../utils/types';
import {
  isRelationValue,
  type RelationValue,
  relationIsMany,
  relationTarget,
} from '../utils/values';

/** Long enough that typing a word is one request, short enough that the list
 *  feels attached to the keyboard. */
const DEBOUNCE_MS = 250;
const RESULT_LIMIT = 10;

/** `null` means "looked up and not there" — a dangling reference, which a
 *  soft-deleted target legitimately produces (design §9). It renders as a
 *  marked chip; it never throws. */
type LabelMap = Record<string, string | null>;

function valuesOf(value: unknown, many: boolean): RelationValue[] {
  if (many) return Array.isArray(value) ? value.filter(isRelationValue) : [];
  return isRelationValue(value) ? [value] : [];
}

/**
 * Picks the target of a `relation` field: `{type, uuid}`, or a list of them
 * when `options.many`.
 *
 * Search runs against `display_title:contains:<q>`, the one filter the index
 * layer supports on that column — `§7.2`'s rule means a free-text search over
 * the payload does not exist, and asking for one returns a 400, not results.
 */
export function RelationPicker({
  field,
  value,
  onChange,
  disabled,
}: {
  field: FieldDef;
  value: unknown;
  onChange: (next: unknown) => void;
  disabled?: boolean;
}) {
  const { t } = useT();
  const target = relationTarget(field);
  const many = relationIsMany(field);
  const selected = useMemo(() => valuesOf(value, many), [value, many]);

  const [labels, setLabels] = useState<LabelMap>({});
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<RecordRead[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const labelsRef = useRef<LabelMap>({});
  labelsRef.current = labels;

  // Resolve the display title of whatever is already selected. A 404 is an
  // expected answer here, not a failure: it marks the chip and moves on.
  useEffect(() => {
    if (!target) return;
    let cancelled = false;
    const missing = selected.map((ref) => ref.uuid).filter((uuid) => !(uuid in labelsRef.current));
    if (missing.length === 0) return;
    void Promise.all(
      missing.map(async (uuid): Promise<readonly [string, string | null] | null> => {
        try {
          const record = await getRecord(target, uuid);
          return [uuid, record.display_title] as const;
        } catch (err) {
          // A 404 is a *fact* about the reference and is cached as one. Any
          // other failure is about the network, so nothing is cached and the
          // chip keeps showing the raw uuid until a later render retries.
          if (err instanceof ApiError && err.status === 404) return [uuid, null] as const;
          return null;
        }
      }),
    ).then((pairs) => {
      if (cancelled) return;
      const resolved = pairs.filter(
        (pair): pair is readonly [string, string | null] => pair !== null,
      );
      if (resolved.length > 0) setLabels((prev) => ({ ...prev, ...Object.fromEntries(resolved) }));
    });
    return () => {
      cancelled = true;
    };
  }, [target, selected]);

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
      listRecords(target, {
        page_size: RESULT_LIMIT,
        filter: buildFilterParam('display_title', 'contains', term),
      })
        .then((page) => {
          if (cancelled) return;
          setResults(page.items);
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
      setLabels((prev) => ({ ...prev, [record.uuid]: record.display_title }));
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
  const removeLabel = t('records.relation.remove', { defaultValue: 'Remove' });

  return (
    <div className="grid gap-2" data-testid={`records-relation-${field.key}`}>
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {selected.map((ref) => {
            const label = labels[ref.uuid];
            const gone = ref.uuid in labels && label === null;
            return (
              <Badge
                key={ref.uuid}
                variant={gone ? 'destructive' : 'secondary'}
                className="gap-1 py-1"
              >
                <span>{gone ? missingLabel : (label ?? ref.uuid)}</span>
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
