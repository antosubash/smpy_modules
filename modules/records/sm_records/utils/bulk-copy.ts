/**
 * What the bulk controls say — the copy, apart from the components.
 *
 * Two reasons it lives here rather than inline. Which actions a view offers
 * is a rule (`trashed` decides, and the two sets never mix), and a rule is
 * worth a test that does not have to mount anything. And every one of these
 * sentences carries a count or a "matching this filter" — the two things an
 * operator has to read correctly before confirming something irreversible —
 * so they are worth asserting on with interpolation actually applied, which
 * a mounted test cannot do (i18next is unconfigured under vitest).
 */

import type { BulkAction } from './api-records';
import type { Translate } from './i18n';
import { keys } from './i18n';

export type BulkActionCopy = {
  action: BulkAction;
  label: string;
  description: string;
  destructive?: boolean;
};

/**
 * The actions this view offers, in the order they are shown.
 *
 * Live rows get Trash / Publish / Unpublish; the Trash view gets Restore and
 * Delete permanently. Never both: restoring a live record and trashing a
 * trashed one are refusals the server would have to spell out, and offering
 * them would be the UI asking to be refused.
 */
export function bulkActions(t: Translate, { count, trashed }: { count: number; trashed: boolean }) {
  if (trashed) {
    return [
      {
        action: 'restore' as const,
        label: t(keys.records.bulk.restore),
        description: t(keys.records.bulk.confirm_restore, {
          count,
        }),
      },
      {
        action: 'purge' as const,
        label: t(keys.records.bulk.purge),
        description: t(keys.records.bulk.confirm_purge, {
          count,
        }),
        destructive: true,
      },
    ];
  }
  return [
    {
      action: 'trash' as const,
      label: t(keys.records.bulk.trash),
      description: t(keys.records.bulk.confirm_trash, {
        count,
      }),
      destructive: true,
    },
    {
      action: 'publish' as const,
      label: t(keys.records.bulk.publish),
      description: t(keys.records.bulk.confirm_publish, {
        count,
      }),
    },
    {
      action: 'unpublish' as const,
      label: t(keys.records.bulk.unpublish),
      description: t(keys.records.bulk.confirm_unpublish, {
        count,
      }),
    },
  ];
}

/**
 * What "Empty trash" is about to delete.
 *
 * Filter-aware on purpose: the button empties what the screen is showing, and
 * an irreversible action whose copy claimed more than it does — or less — is
 * the one mistake this dialog exists to prevent.
 *
 * `capped` is the listing's `total_capped`: the number is a floor rather than
 * the number, so the sentence says "more than" instead of asserting a total
 * nobody counted — and it names what to type instead, since there is no exact
 * count to ask for. That is the type's key, the way a repository host asks
 * for a repository name before deleting one.
 */
export function emptyTrashDescription(
  t: Translate,
  {
    count,
    filtered,
    capped = false,
    typeKey,
  }: { count: number; filtered: boolean; capped?: boolean; typeKey: string },
): string {
  if (capped) {
    return filtered
      ? t(keys.records.bulk.confirm_empty_trash_filtered_capped, {
          count,
          key: typeKey,
        })
      : t(keys.records.bulk.confirm_empty_trash_capped, {
          count,
          key: typeKey,
        });
  }
  return filtered
    ? t(keys.records.bulk.confirm_empty_trash_filtered, {
        count,
      })
    : t(keys.records.bulk.confirm_empty_trash, {
        count,
      });
}
