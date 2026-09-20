import { Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { type ReactNode, useState } from 'react';

import { listReferrers } from '../utils/api-history';
import type { ReferrerRead } from '../utils/types';
import { ConfirmDialog } from './ConfirmDialog';

/** Referrers loaded live and not `is_deleted`: a trashed referrer neither
 *  blocks a `restrict` delete nor is followed by a `cascade` (design §9), so
 *  it plays no part in what this dialog says will happen. */
function livingByOnDelete(items: ReferrerRead[], onDelete: string): ReferrerRead[] {
  return items.filter((item) => item.on_delete === onDelete && !item.is_deleted);
}

function ReferrerLink({ item }: { item: ReferrerRead }) {
  return (
    <Link href={`/admin/records/${item.type_key}/${item.uuid}`} className="hover:underline">
      {item.display_title}
    </Link>
  );
}

// See `RecordList.tsx` for why `t` is typed this loosely here.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

/** Exported only for `RecordDeleteDialog.test.tsx`: the dialog's own text is
 *  pure given `loading`/`loadError`/`referrers`, so it is tested directly
 *  rather than through the interactive `ConfirmDialog` this file has no
 *  DOM/testing-library setup to drive. */
export function DialogBody({
  t,
  loading,
  loadError,
  referrers,
}: {
  t: Translate;
  loading: boolean;
  loadError: string | null;
  referrers: ReferrerRead[] | null;
}) {
  if (loading) {
    return (
      <span data-testid="records-delete-dialog-checking">
        {t('records.records.delete_checking', {
          defaultValue: 'Checking what references this record…',
        })}
      </span>
    );
  }
  if (loadError) {
    return <span className="text-destructive">{loadError}</span>;
  }
  const plain = t('records.records.confirm_delete', { defaultValue: 'Delete this record?' });
  if (!referrers || referrers.length === 0) return plain;

  const restrictors = livingByOnDelete(referrers, 'restrict');
  const setNulls = livingByOnDelete(referrers, 'set_null');
  const cascades = livingByOnDelete(referrers, 'cascade');
  if (restrictors.length === 0 && setNulls.length === 0 && cascades.length === 0) return plain;

  return (
    <div className="space-y-2" data-testid="records-delete-dialog-referrers">
      {restrictors.length > 0 && (
        <>
          <p>
            {t('records.records.delete_blocked', {
              count: restrictors.length,
              defaultValue: '{count} record will block this delete',
              defaultValue_other: '{count} records will block this delete',
            })}
          </p>
          <ul className="list-disc space-y-1 pl-5">
            {restrictors.map((item) => (
              <li key={`${item.type_key}:${item.uuid}:${item.field_key}`}>
                <ReferrerLink item={item} /> ({item.type_label} · {item.field_label})
              </li>
            ))}
          </ul>
          <p>
            {t('records.records.delete_blocked_help', {
              defaultValue: 'Detach or change these references before deleting.',
            })}
          </p>
        </>
      )}
      {restrictors.length === 0 && setNulls.length > 0 && (
        <p>
          {t('records.records.delete_set_null', {
            count: setNulls.length,
            defaultValue: '{count} record will have this reference cleared',
            defaultValue_other: '{count} records will have this reference cleared',
          })}
        </p>
      )}
      {restrictors.length === 0 && cascades.length > 0 && (
        <>
          <p>
            {t('records.records.delete_cascade', {
              count: cascades.length,
              defaultValue: '{count} record will be deleted too',
              defaultValue_other: '{count} records will be deleted too',
            })}
          </p>
          <ul className="list-disc space-y-1 pl-5">
            {cascades.map((item) => (
              <li key={`${item.type_key}:${item.uuid}:${item.field_key}`}>
                {item.display_title} ({item.type_label})
              </li>
            ))}
          </ul>
        </>
      )}
      {restrictors.length === 0 && <p>{plain}</p>}
    </div>
  );
}

/**
 * The soft-delete confirmation, aware of what points at the record (design
 * §9): before asking, it fetches the referrers and says what deleting would
 * actually do — block (`restrict`, confirm disabled), clear a reference
 * (`set_null`) or take other records with it (`cascade`, listed). Zero
 * referrers falls through to the same plain "Delete this record?" the
 * dialog always asked.
 *
 * The fetch is a snapshot, not a lock: a `restrict` referrer created between
 * the fetch and the confirm click still comes back as the API's own `409`
 * (`ReferencedByOthers`), which `ConfirmDialog`'s generic error state already
 * surfaces — this dialog does not need to special-case that race.
 */
export function RecordDeleteDialog({
  typeKey,
  uuid,
  trigger,
  onConfirm,
}: {
  typeKey: string;
  uuid: string;
  trigger: ReactNode;
  onConfirm: () => Promise<unknown>;
}) {
  const { t } = useT();
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [referrers, setReferrers] = useState<ReferrerRead[] | null>(null);

  const load = async () => {
    setLoading(true);
    setLoadError(null);
    setReferrers(null);
    try {
      // Large enough to classify every referrer a hand-built graph is likely
      // to have without paging inside a confirmation dialog; `total` still
      // rides along for a caller that wants the honest count beyond it.
      const resp = await listReferrers(typeKey, uuid, { page: 1, page_size: 100 });
      setReferrers(resp.items);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const blocked = livingByOnDelete(referrers ?? [], 'restrict').length > 0;

  return (
    <ConfirmDialog
      trigger={trigger}
      title={t('records.records.delete', { defaultValue: 'Delete' })}
      description={
        <DialogBody t={t} loading={loading} loadError={loadError} referrers={referrers} />
      }
      confirmLabel={t('records.records.delete', { defaultValue: 'Delete' })}
      cancelLabel={t('records.editor.cancel', { defaultValue: 'Cancel' })}
      pendingLabel={t('records.editor.saving', { defaultValue: 'Saving…' })}
      destructive
      confirmDisabled={loading || blocked}
      onOpenChange={(next) => {
        if (next) void load();
      }}
      onConfirm={onConfirm}
    />
  );
}
