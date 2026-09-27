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
import type { Translate } from './translate';

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
        label: t('records.bulk.restore', { defaultValue: 'Restore' }),
        description: t('records.bulk.confirm_restore', {
          count,
          defaultValue: 'Restore {count} records from the Trash?',
          defaultValue_one: 'Restore this record from the Trash?',
        }),
      },
      {
        action: 'purge' as const,
        label: t('records.bulk.purge', { defaultValue: 'Delete permanently' }),
        description: t('records.bulk.confirm_purge', {
          count,
          defaultValue: 'This cannot be undone. Delete {count} records permanently?',
          defaultValue_one: 'This cannot be undone. Delete this record permanently?',
        }),
        destructive: true,
      },
    ];
  }
  return [
    {
      action: 'trash' as const,
      label: t('records.bulk.trash', { defaultValue: 'Move to Trash' }),
      description: t('records.bulk.confirm_trash', {
        count,
        defaultValue:
          'Move {count} records to the Trash? You can restore them until they are deleted permanently.',
        defaultValue_one:
          'Move this record to the Trash? You can restore it until it is deleted permanently.',
      }),
      destructive: true,
    },
    {
      action: 'publish' as const,
      label: t('records.bulk.publish', { defaultValue: 'Publish' }),
      description: t('records.bulk.confirm_publish', {
        count,
        defaultValue: 'Publish {count} records?',
        defaultValue_one: 'Publish this record?',
      }),
    },
    {
      action: 'unpublish' as const,
      label: t('records.bulk.unpublish', { defaultValue: 'Unpublish' }),
      description: t('records.bulk.confirm_unpublish', {
        count,
        defaultValue: 'Return {count} records to draft? They stop being served publicly.',
        defaultValue_one: 'Return this record to draft? It stops being served publicly.',
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
      ? t('records.bulk.confirm_empty_trash_filtered_capped', {
          count,
          key: typeKey,
          defaultValue:
            'This permanently deletes more than {count} trashed records matching this filter. Type {key} to confirm.',
        })
      : t('records.bulk.confirm_empty_trash_capped', {
          count,
          key: typeKey,
          defaultValue:
            'This permanently deletes more than {count} trashed records. Type {key} to confirm.',
        });
  }
  return filtered
    ? t('records.bulk.confirm_empty_trash_filtered', {
        count,
        defaultValue:
          'Delete the {count} trashed records matching this filter permanently? This cannot be undone.',
        defaultValue_one:
          'Delete the {count} trashed record matching this filter permanently? This cannot be undone.',
      })
    : t('records.bulk.confirm_empty_trash', {
        count,
        defaultValue: 'Delete all {count} trashed records permanently? This cannot be undone.',
        defaultValue_one: 'Delete the {count} trashed record permanently? This cannot be undone.',
      });
}
