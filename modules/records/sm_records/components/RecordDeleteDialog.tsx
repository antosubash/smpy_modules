import { Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { type ReactNode, useState } from 'react';

import { listReferrers } from '../utils/api-history';
import type { Translate } from '../utils/translate';
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

/** Exported only for `RecordDeleteDialog.test.tsx`: the dialog's own text is
 *  pure given `loading`/`loadError`/`referrers`, so it is tested directly
 *  rather than through the interactive `ConfirmDialog` this file has no
 *  DOM/testing-library setup to drive.
 *
 * A sentence, always — `ConfirmDialog`'s `description` renders inside a real
 * `<p>` (L6), so this never returns block markup (a list, another `<p>`);
 * that lives in `DialogDetails` instead, passed as `body`. */
export function DialogDescription({
  t,
  loading,
  loadError,
}: {
  t: Translate;
  loading: boolean;
  loadError: string | null;
}): ReactNode {
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
  // Names the Trash and says the delete is reversible (UX-R8): this is a
  // soft delete the record can be restored from until it is purged, and a
  // dialog that said "Delete this record?" presented a safe, reversible
  // action as a one-way door — the module's safety net was invisible on the
  // one screen that should mention it.
  return t('records.records.confirm_delete', {
    defaultValue:
      'Move this record to the Trash? You can restore it until it is deleted permanently.',
  });
}

/** The consequences of deleting, when there are any worth naming — `null`
 *  while still loading, on an error, or when nothing points at this record
 *  in a way that matters. Block content (lists, several paragraphs) on
 *  purpose: rendered as `ConfirmDialog`'s `body`, outside the description
 *  `<p>` (L6), never inside it. */
export function DialogDetails({
  t,
  loading,
  loadError,
  referrers,
}: {
  t: Translate;
  loading: boolean;
  loadError: string | null;
  referrers: ReferrerRead[] | null;
}): ReactNode {
  if (loading || loadError || !referrers || referrers.length === 0) return null;

  const restrictors = livingByOnDelete(referrers, 'restrict');
  const setNulls = livingByOnDelete(referrers, 'set_null');
  const cascades = livingByOnDelete(referrers, 'cascade');
  if (restrictors.length === 0 && setNulls.length === 0 && cascades.length === 0) return null;

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
    </div>
  );
}

/**
 * The soft-delete confirmation, aware of what points at the record (design
 * §9): before asking, it fetches the referrers and says what deleting would
 * actually do — block (`restrict`, confirm disabled), clear a reference
 * (`set_null`) or take other records with it (`cascade`, listed). Zero
 * referrers falls through to the plain "Move this record to the Trash?"
 * every delete asks.
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

  // U15: the trigger (a table/editor row action) stays "Delete" — the
  // conventional, unambiguous affordance for the action a person is
  // choosing. The dialog itself is a different surface: its title and
  // confirm button used to say "Delete" too, while its own body carefully
  // said "Move this record to the Trash" — the one word the description
  // avoided was the one everything around it used. Say what actually
  // happens, consistently, once the dialog is open.
  const moveToTrash = t('records.records.move_to_trash', { defaultValue: 'Move to Trash' });
  return (
    <ConfirmDialog
      trigger={trigger}
      title={moveToTrash}
      description={<DialogDescription t={t} loading={loading} loadError={loadError} />}
      body={<DialogDetails t={t} loading={loading} loadError={loadError} referrers={referrers} />}
      confirmLabel={moveToTrash}
      destructive
      confirmDisabled={loading || blocked}
      onOpenChange={(next) => {
        if (next) void load();
      }}
      onConfirm={onConfirm}
    />
  );
}
