import { router } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useEffect, useState } from 'react';

import { reindexType } from '../../utils/api';
import type { TypeRead } from '../../utils/types';
import { pendingEntries, shouldPoll } from './reindexPending';

const POLL_MS = 5000;

/**
 * `type.reindex_pending` as a live notice (design §8.5/§8.9): a schema
 * change that moved an indexed field between index tables, or changed
 * `display_field`, leaves that field (or `"*"` — the whole type)
 * unfilterable until the background reindex finishes. Polls
 * `router.reload({ only: ['type'] })` every ~5s while anything is still
 * pending, and stops the moment it isn't — a field stuck in `indexing`
 * because a worker restarted mid-deploy is exactly the case §8.9's health
 * check exists for, so "Reindex now" is the manual recovery for it.
 *
 * `type` is the caller's own up-to-date snapshot, not a copy frozen at
 * mount: `router.reload` only refreshes the Inertia prop upstream, so
 * `TypeEditor` keeps its `current` state (what it passes here) in sync with
 * that prop (F4) — otherwise `entries` never empties, this effect's
 * `[entries.length]` dependency never changes, and both the banner and the
 * poll outlive the rebuild.
 */
export function ReindexStatus({ type }: { type: TypeRead }) {
  const { t } = useT();
  const [pending, setPending] = useState(false);
  const entries = pendingEntries(type.reindex_pending);
  const polling = shouldPoll(entries);

  useEffect(() => {
    if (!polling) return;
    const id = setInterval(() => {
      router.reload({ only: ['type'] });
    }, POLL_MS);
    return () => clearInterval(id);
  }, [polling]);

  if (!polling) return null;

  const triggerReindex = async () => {
    setPending(true);
    try {
      await reindexType(type.key);
      router.reload({ only: ['type'] });
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-blue-500/50 bg-blue-500/10 p-3 text-sm">
      <div>
        <p className="font-medium">
          {t('records.type_editor.reindex.notice', {
            defaultValue: 'Rebuilding the index for:',
          })}
        </p>
        <ul className="mt-1 space-y-0.5">
          {entries.map((entry) => (
            <li key={entry.key}>
              {entry.wholeType
                ? t('records.type_editor.reindex.whole_type', { defaultValue: 'Whole type' })
                : entry.key}
              {' — '}
              {t('records.type_editor.reindex.since', {
                time: entry.since,
                defaultValue: 'since {{time}}',
              })}
            </li>
          ))}
        </ul>
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={pending}
        onClick={() => void triggerReindex()}
      >
        {pending
          ? t('records.editor.saving', { defaultValue: 'Saving…' })
          : t('records.type_editor.reindex.reindex_now', { defaultValue: 'Reindex now' })}
      </Button>
    </div>
  );
}
