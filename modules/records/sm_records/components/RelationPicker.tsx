import { useT } from '@simple-module-py/i18n';
import { Input } from '@simple-module-py/ui/components/ui/input';
import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useRelationLabels } from '../hooks/useRelationLabels';
import { searchByTitle } from '../utils/relation-search';
import type { ExpandedRef, FieldDef, RecordRead } from '../utils/types';
import {
  isRelationValue,
  type RelationValue,
  relationIsMany,
  relationTarget,
} from '../utils/values';
import { RelationChips } from './RelationChips';

/** Long enough that typing a word is one request, short enough that the list
 *  feels attached to the keyboard. */
const DEBOUNCE_MS = 250;

function valuesOf(value: unknown, many: boolean): RelationValue[] {
  if (many) return Array.isArray(value) ? value.filter(isRelationValue) : [];
  return isRelationValue(value) ? [value] : [];
}

/**
 * Picks the target of a `relation` field: `{type, uuid}`, or a list of them
 * when `options.many`.
 *
 * A WAI-ARIA combobox (UX review R20), not a text box with buttons under it:
 * the input owns `aria-expanded`/`aria-activedescendant`, the results are a
 * `listbox` of `option`s, Up/Down move the active option without moving
 * focus, Enter takes it and Escape dismisses the list. `aria-live` announces
 * how many results arrived, which nothing said before.
 *
 * The whole control is a `group` labelled by the field's own label (R11) —
 * `FieldShell` hands that id down, because a filled single-value relation has
 * no focusable input left for the label to point at.
 */
export function RelationPicker({
  field,
  value,
  onChange,
  disabled,
  expanded,
  labelId,
}: {
  field: FieldDef;
  value: unknown;
  onChange: (next: unknown) => void;
  disabled?: boolean;
  /** This field's slice of the record's `expanded` (design §9), when the
   *  page already resolved it — the editor's own load always does. Consulted
   *  before falling back to the per-uuid lookup, so a value the page
   *  expanded is never fetched twice. */
  expanded?: ExpandedRef[];
  /** `FieldShell`'s label id — the group's accessible name. */
  labelId?: string;
}) {
  const { t } = useT();
  const target = relationTarget(field);
  const many = relationIsMany(field);
  const selected = useMemo(() => valuesOf(value, many), [value, many]);
  const { labels, remember } = useRelationLabels(target, selected, expanded);

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<RecordRead[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const [dismissed, setDismissed] = useState(false);

  const listboxId = `records-relation-listbox-${field.key}`;
  const optionId = (uuid: string) => `records-relation-option-${field.key}-${uuid}`;
  const open = query.trim() !== '' && !dismissed;

  useEffect(() => {
    const term = query.trim();
    if (!target || term === '') {
      setResults([]);
      setSearchError(null);
      // A request emptied mid-flight otherwise leaves `searching` stuck
      // `true` forever (L8) — currently invisible (the results box is gated
      // on `query.trim() !== ''`), but the two branches should agree on this
      // flag regardless.
      setSearching(false);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const timer = setTimeout(() => {
      searchByTitle(target, term)
        .then((items) => {
          if (cancelled) return;
          setResults(items);
          setActive(0);
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
      remember(record);
      const ref: RelationValue = { type: target, uuid: record.uuid };
      if (!many) {
        onChange(ref);
      } else if (!selected.some((item) => item.uuid === record.uuid)) {
        onChange([...selected, ref]);
      }
      setQuery('');
      setResults([]);
      setActive(0);
    },
    [many, onChange, selected, target, remember],
  );

  const remove = useCallback(
    (uuid: string) => {
      onChange(many ? selected.filter((item) => item.uuid !== uuid) : null);
    },
    [many, onChange, selected],
  );

  /** Up/Down move the active option, Enter takes it, Escape closes the list
   *  and leaves the text alone — the keyboard contract the pattern owes. */
  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      // `preventDefault` because this is a `type="search"` input, and the
      // browser's own Escape *clears* it. The pattern says the first Escape
      // dismisses the list and leaves the text alone; losing what you typed
      // is exactly the surprise the key is supposed to undo.
      event.preventDefault();
      setDismissed(true);
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (results.length === 0) return;
      event.preventDefault();
      setDismissed(false);
      const step = event.key === 'ArrowDown' ? 1 : -1;
      setActive((prev) => (prev + step + results.length) % results.length);
      return;
    }
    if (event.key === 'Enter') {
      // Always swallowed while the list is open, so Enter never submits
      // whatever form the editor grows around this.
      if (!open || results.length === 0) return;
      event.preventDefault();
      const chosen = results[Math.min(active, results.length - 1)];
      if (chosen) pick(chosen);
    }
  };

  const activeIndex = Math.min(active, Math.max(results.length - 1, 0));
  const activeUuid = open && results.length > 0 ? results[activeIndex]?.uuid : undefined;

  return (
    // A `fieldset`, not a `div role="group"`: same role, and the element
    // the platform already has for "these controls belong together" (R11).
    <fieldset
      className="grid gap-2"
      aria-labelledby={labelId}
      data-testid={`records-relation-${field.key}`}
    >
      <RelationChips selected={selected} labels={labels} disabled={disabled} onRemove={remove} />

      {(many || selected.length === 0) && (
        <Input
          type="search"
          role="combobox"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={activeUuid ? optionId(activeUuid) : undefined}
          value={query}
          disabled={disabled || !target}
          placeholder={t('records.relation.search_placeholder', {
            defaultValue: 'Search by title…',
          })}
          // Two relation fields on one form gave two identically named search
          // boxes; the field's own label is what tells them apart (R11).
          aria-label={t('records.relation.search_field_label', {
            label: field.label,
            defaultValue: 'Search {label}',
          })}
          onChange={(event) => {
            setQuery(event.target.value);
            setDismissed(false);
          }}
          onKeyDown={onKeyDown}
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

      {/* Outside the `open` gate on purpose: a live region has to be in the
          document *before* it is filled, or the first announcement is the
          region appearing rather than what it says. */}
      <p className="sr-only" role="status" aria-live="polite">
        {open && !searching
          ? t('records.relation.result_count', {
              count: results.length,
              defaultValue: '{count} record found',
              defaultValue_other: '{count} records found',
            })
          : ''}
      </p>

      {open && (
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
          {/* A listbox of options is the ARIA pattern this control
              implements; no HTML element carries those roles. */}
          <div
            id={listboxId}
            role="listbox"
            aria-labelledby={labelId}
            className="max-h-60 overflow-auto"
          >
            {results.map((record, index) => (
              <div
                key={record.uuid}
                id={optionId(record.uuid)}
                role="option"
                // Never in the tab order: focus stays on the input and
                // `aria-activedescendant` is what moves, which is the whole
                // point of the pattern. `-1` is here so the option can still
                // be reached programmatically.
                tabIndex={-1}
                aria-selected={index === activeIndex}
                // `onMouseDown`, not `onClick`: the input must not lose focus
                // before the pick lands, or the list closes under the pointer.
                onMouseDown={(event) => {
                  event.preventDefault();
                  if (!disabled) pick(record);
                }}
                onMouseEnter={() => setActive(index)}
                className={`cursor-pointer px-3 py-2 text-sm ${
                  index === activeIndex ? 'bg-accent' : ''
                }`}
              >
                {record.display_title}
              </div>
            ))}
          </div>
        </div>
      )}
    </fieldset>
  );
}
