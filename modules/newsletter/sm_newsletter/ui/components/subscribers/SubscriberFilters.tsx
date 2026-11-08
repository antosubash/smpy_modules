/** The list's filters: a search box, a tag select (when the list has a `tags`
 *  field) and a segment select. The search text stays in the caller's state (C5). */

import { Input } from '@simple-module-py/ui/components/ui/input';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';

import { keys, useT } from '../../utils/i18n';
import type { ListField, Segment } from '../../utils/types';

/** The API's cap on the search text (`sm_records.contracts.newsletter_admin.MAX_SEARCH_LEN`); more is a 422. */
export const MAX_SEARCH = 200;

interface Props {
  q: string;
  tag: string;
  segment: string;
  fields: ListField[] | null;
  segments: Segment[];
  onQ: (q: string) => void;
  onTag: (tag: string) => void;
  onSegment: (segment: string) => void;
}

export function SubscriberFilters({
  q,
  tag,
  segment,
  fields,
  segments,
  onQ,
  onTag,
  onSegment,
}: Props) {
  const { t } = useT();
  const copy = keys.newsletter.subscribers;
  const tags = fields?.find((f) => f.key === 'tags');
  return (
    <div className="mb-4 flex flex-wrap gap-2">
      <Input
        type="search"
        className="max-w-xs"
        aria-label={t(copy.search_label)}
        placeholder={t(copy.search_placeholder)}
        autoComplete="off"
        maxLength={MAX_SEARCH}
        value={q}
        onChange={(e) => onQ(e.target.value)}
      />
      {tags && (
        <NativeSelect
          aria-label={t(copy.tag_label)}
          value={tag}
          onChange={(e) => onTag(e.target.value)}
        >
          <option value="">{t(copy.tag_all)}</option>
          {tags.choices.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </NativeSelect>
      )}
      <NativeSelect
        aria-label={t(copy.segment_label)}
        value={segment}
        onChange={(e) => onSegment(e.target.value)}
      >
        <option value="">{t(copy.segment_all)}</option>
        {segments.map((s) => (
          <option key={s.id} value={String(s.id)}>
            {s.name}
          </option>
        ))}
      </NativeSelect>
    </div>
  );
}
