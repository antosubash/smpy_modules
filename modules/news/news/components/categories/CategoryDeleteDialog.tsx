import { ConfirmDialog } from '@simple-module-py/pagebuilder/pagebuilder/components/ConfirmDialog';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import { useState } from 'react';

import type { CategoryRead } from '../../utils/taxonomyApi';
import { isManaged } from '../../utils/taxonomyApi';

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
  const [reassignTo, setReassignTo] = useState(UNCATEGORISED);

  const destinations = all.filter((c) => isManaged(c) && c.id !== category.id);
  const count = category.article_count;

  return (
    <ConfirmDialog
      trigger={trigger}
      level={count === 0 ? 'low' : 'medium'}
      title={`Delete "${category.name}"?`}
      description={
        count === 0 ? (
          <>The category is empty, so nothing moves. The public filter loses one entry.</>
        ) : (
          <>
            {count} {count === 1 ? 'article' : 'articles'} will move to{' '}
            <strong>{reassignTo || 'Uncategorised'}</strong>. Nothing is deleted with the category —
            the articles keep their body, slug and date.
          </>
        )
      }
      confirmLabel="Delete category"
      onConfirm={() => onConfirm(reassignTo)}
    >
      {count > 0 && (
        <>
          <Label htmlFor={REASSIGN_SELECT_ID}>Move its articles to</Label>
          <NativeSelect
            id={REASSIGN_SELECT_ID}
            value={reassignTo}
            onChange={(e) => setReassignTo(e.target.value)}
          >
            <option value={UNCATEGORISED}>Uncategorised</option>
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
