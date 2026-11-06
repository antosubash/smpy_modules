/**
 * The field of an article or page card: search, choose, refresh (ruling R9).
 *
 * A card is a server-side *snapshot* of its source. Choosing a hit asks the
 * server for one (`api.snapshot`) and replaces the whole block's props with
 * it, keeping the block id. That is several props at once, which a field's
 * own `onChange` cannot write, so it goes through Puck's `replace` action.
 * *Refresh* re-snapshots the stored draft server-side through the editor page
 * (`useEditorActions`), which flushes the autosave first.
 *
 * When the integration is not available (ruling R2) both are disabled with a
 * note; the card's snapshot still renders and the block can still be deleted.
 */

import {
  type CustomField,
  createUsePuck,
  FieldLabel,
  type PuckApi,
  useGetPuck,
} from '@puckeditor/core';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { useEffect, useState } from 'react';

import { SEARCH_DEBOUNCE_MS } from '../../hooks/useCampaignList';
import { api, errorMessage } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import type { CardHit, CardKind, CardSnapshot } from '../../utils/types';
import { useEditorActions } from './editorActions';

const CARD_TYPE: Record<CardKind, string> = { article: 'ArticleCard', page: 'PageCard' };

/** The parts of Puck's API `applySnapshot` uses. */
type PuckLike = Pick<PuckApi, 'getItemById' | 'getSelectorForId' | 'dispatch'>;

/**
 * Write `snapshot` into the card block `blockId`, keeping its id.
 *
 * Found by id, not by selection, and only if it is still a card of `kind`:
 * the block may have been deleted, or another block selected, while the
 * snapshot request was out. Returns whether anything was written.
 */
export function applySnapshot(
  puck: PuckLike,
  blockId: string,
  kind: CardKind,
  snapshot: CardSnapshot,
): boolean {
  const item = puck.getItemById(blockId);
  const at = puck.getSelectorForId(blockId);
  if (!item || !at || item.type !== CARD_TYPE[kind]) return false;
  puck.dispatch({
    type: 'replace',
    destinationIndex: at.index,
    destinationZone: at.zone,
    data: { type: item.type, props: { ...snapshot, id: blockId } },
  });
  return true;
}

const copy = keys.newsletter.editor.card;
const usePuck = createUsePuck();

function useCardSearch(kind: CardKind, enabled: boolean) {
  const { t } = useT();
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<CardHit[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setHits(null);
      api
        .searchCards(kind, q, controller.signal)
        .then((found) => {
          setError(null);
          setHits(found);
        })
        .catch((e) => {
          if (!controller.signal.aborted) setError(errorMessage(e, t));
        });
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [kind, q, enabled, t]);

  return { q, setQ, hits, error, setError };
}

interface CardPickerProps {
  kind: CardKind;
  available: boolean;
  readOnly?: boolean;
}

export function CardPicker({ kind, available, readOnly }: CardPickerProps) {
  const { t, locale } = useT();
  const selected = usePuck((s) => s.selectedItem);
  const getPuck = useGetPuck();
  const { refresh } = useEditorActions();
  const [busy, setBusy] = useState(false);
  const disabled = !available || readOnly === true;
  const search = useCardSearch(kind, !disabled);
  const current = (selected?.props ?? {}) as Partial<CardSnapshot>;
  const blockId = typeof current.id === 'string' ? current.id : null;

  async function pick(hit: CardHit) {
    // The block this field belongs to, fixed before the request: the writer
    // may select another block while it is out.
    const target = getPuck().selectedItem?.props.id;
    if (typeof target !== 'string') return;
    setBusy(true);
    try {
      const snapshot = await api.snapshot(kind, hit.source_id);
      applySnapshot(getPuck(), target, kind, snapshot);
      search.setError(null);
    } catch (e) {
      search.setError(errorMessage(e, t));
    } finally {
      setBusy(false);
    }
  }

  async function onRefresh() {
    if (!blockId) return;
    setBusy(true);
    try {
      await refresh(blockId);
    } finally {
      setBusy(false);
    }
  }

  const copiedAt = current.snapshot_at ? new Date(current.snapshot_at) : null;

  return (
    <FieldLabel label={t(kind === 'article' ? copy.article : copy.page)}>
      <div className="space-y-2">
        <div className="rounded border p-2 text-sm">
          <p className="text-xs text-muted-foreground">{t(copy.current)}</p>
          {current.source_id ? (
            <>
              <p className="font-medium">{current.title}</p>
              {copiedAt && !Number.isNaN(copiedAt.getTime()) && (
                <p className="text-xs text-muted-foreground">
                  {t(copy.copied_at, {
                    date: copiedAt.toLocaleString(locale, {
                      dateStyle: 'medium',
                      timeStyle: 'short',
                    }),
                  })}
                </p>
              )}
            </>
          ) : (
            <p className="text-muted-foreground">{t(copy.none)}</p>
          )}
        </div>

        {!available && (
          <p className="text-xs text-muted-foreground">
            {t(keys.newsletter.editor.integration_missing)}
          </p>
        )}

        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled || busy || !current.source_id}
          onClick={() => void onRefresh()}
        >
          {busy ? t(copy.refreshing) : t(copy.refresh)}
        </Button>

        <Input
          type="search"
          aria-label={t(copy.search_label)}
          placeholder={t(kind === 'article' ? copy.search_article : copy.search_page)}
          value={search.q}
          disabled={disabled}
          onChange={(e) => search.setQ(e.target.value)}
        />
        {search.error && <p className="text-xs text-destructive">{search.error}</p>}
        {!disabled && !search.error && (
          <CardHits hits={search.hits} busy={busy} onPick={(hit) => void pick(hit)} />
        )}
      </div>
    </FieldLabel>
  );
}

function CardHits(props: {
  hits: CardHit[] | null;
  busy: boolean;
  onPick: (hit: CardHit) => void;
}) {
  const { t } = useT();
  const { hits, busy, onPick } = props;
  if (hits === null) return <p className="text-xs text-muted-foreground">{t(copy.searching)}</p>;
  if (hits.length === 0) {
    return <p className="text-xs text-muted-foreground">{t(copy.no_results)}</p>;
  }
  return (
    <ul className="max-h-64 space-y-1 overflow-y-auto">
      {hits.map((hit) => (
        <li key={`${hit.kind}-${hit.source_id}`}>
          <button
            type="button"
            disabled={busy}
            className="w-full rounded border p-2 text-left text-sm hover:bg-muted disabled:opacity-50"
            onClick={() => onPick(hit)}
          >
            <span className="block font-medium">{hit.title}</span>
            {hit.excerpt && (
              <span className="line-clamp-2 block text-xs text-muted-foreground">
                {hit.excerpt}
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

/** A card block's one field. `available` is the integration's capability. */
export function cardField(kind: CardKind, available: boolean): CustomField<number> {
  return {
    type: 'custom',
    render: ({ readOnly }) => <CardPicker kind={kind} available={available} readOnly={readOnly} />,
  };
}
