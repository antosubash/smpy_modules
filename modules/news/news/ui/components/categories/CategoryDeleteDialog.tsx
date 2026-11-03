import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useState } from 'react';
import { keys, useT } from '../../utils/i18n';
import type { CategoryRead } from '../../utils/taxonomyApi';
import { isManaged } from '../../utils/taxonomyApi';
import { ConfirmDialog } from '../ConfirmDialog';

const REASSIGN_SELECT_ID = 'news-category-reassign';
const UNCATEGORISED = '';

interface Props {
  category: CategoryRead;
  /** Every category, so the dialog can offer the others as destinations. */
  all: CategoryRead[];
  trigger: React.ReactNode;
  onConfirm: (reassignTo: string) => Promise<unknown>;
}

/** Delete a category, asking where its articles go first.
 *
 * The question is not optional. A category is the only grouping an article has,
 * so deleting one silently would leave its articles ungrouped without anyone
 * choosing that — which is why Uncategorised is an explicit option rather than
 * an implicit fallback.
 *
 * The level tracks the count: an empty category is genuinely cheap to delete,
 * and asking for the same ceremony there teaches people to ignore the ceremony
 * when it matters.
 */
export function CategoryDeleteDialog({ category, all, trigger, onConfirm }: Props) {
  const { t } = useT();
  const [reassignTo, setReassignTo] = useState(UNCATEGORISED);

  const destinations = all.filter((c) => isManaged(c) && c.id !== category.id);
  const count = category.article_count;

  return (
    <ConfirmDialog
      trigger={trigger}
      level={count === 0 ? 'low' : 'medium'}
      title={t(keys.news.categories.delete_title, { name: category.name })}
      // One catalogue entry rather than a sentence assembled around a
      // <strong>: the destination and the count both move in a translation,
      // and splitting them into fragments is what makes that impossible.
      description={
        count === 0
          ? t(keys.news.categories.delete_empty)
          : t(keys.news.categories.delete_moving, {
              count,
              destination: reassignTo || t(keys.news.categories.uncategorised),
            })
      }
      confirmLabel={t(keys.news.categories.delete_confirm)}
      onConfirm={() => onConfirm(reassignTo)}
    >
      {count > 0 && (
        <>
          <Label htmlFor={REASSIGN_SELECT_ID}>{t(keys.news.categories.reassign_label)}</Label>
          <NativeSelect
            id={REASSIGN_SELECT_ID}
            value={reassignTo}
            onChange={(e) => setReassignTo(e.target.value)}
          >
            <option value={UNCATEGORISED}>{t(keys.news.categories.uncategorised)}</option>
            {destinations.map((c) => (
              <option key={c.id} value={c.name}>
                {c.name}
              </option>
            ))}
          </NativeSelect>
        </>
      )}
    </ConfirmDialog>
  );
}
