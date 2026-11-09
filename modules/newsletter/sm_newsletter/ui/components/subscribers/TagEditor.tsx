/** A subscriber's tags: one checkbox per tag the list defines, saved as a diff.
 *
 *  Only the `tags` field's choices are offered (the server refuses any other tag
 *  with `unknown_tag`). Disabled, it is a read-only list. */

import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useEffect, useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import type { FieldChoice } from '../../utils/types';

interface Props {
  tags: string[];
  choices: FieldChoice[];
  disabled: boolean;
  onSave: (add: string[], remove: string[]) => Promise<void>;
}

export function TagEditor({ tags, choices, disabled, onSave }: Props) {
  const { t } = useT();
  const [picked, setPicked] = useState<string[]>(tags);
  const [saving, setSaving] = useState(false);
  const key = tags.join('\u0000');

  // The saved tags changed (after a save or a reload): start from them again.
  // biome-ignore lint/correctness/useExhaustiveDependencies: `key` stands for `tags`
  useEffect(() => setPicked(tags), [key]);

  const labelOf = (value: string) => choices.find((c) => c.value === value)?.label ?? value;
  if (disabled) {
    return (
      <div className="flex flex-wrap gap-1">
        {tags.map((tag) => (
          <Badge key={tag} variant="secondary">
            {labelOf(tag)}
          </Badge>
        ))}
      </div>
    );
  }

  const add = choices.map((c) => c.value).filter((v) => picked.includes(v) && !tags.includes(v));
  const remove = tags.filter((v) => !picked.includes(v) && choices.some((c) => c.value === v));
  const toggle = (value: string) =>
    setPicked((p) => (p.includes(value) ? p.filter((v) => v !== value) : [...p, value]));

  const save = async () => {
    setSaving(true);
    try {
      await onSave(add, remove);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {choices.map((c) => (
          <label key={c.value} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={picked.includes(c.value)}
              disabled={saving}
              onChange={() => toggle(c.value)}
            />
            {c.label}
          </label>
        ))}
      </div>
      <div>
        <Button
          type="button"
          size="sm"
          disabled={saving || (add.length === 0 && remove.length === 0)}
          onClick={() => void save()}
        >
          {t(keys.newsletter.subscribers.detail.tags_save)}
        </Button>
      </div>
    </div>
  );
}
